"""Request limits key on the visitor's address, and trust Vercel's forwarding header only on Vercel."""


def test_vercel_client_address_header_is_trusted_only_on_vercel(app,monkeypatch):
    def burst(forwarded,count=6):
        statuses=[]
        for i in range(count):
            client=app.test_client()
            client.get("/")
            with client.session_transaction() as sess: token=sess["csrf"]
            statuses.append(client.post("/demo",data=dict(csrf_token=token,reset="1"),headers={"X-Vercel-Forwarded-For":forwarded(i)}).status_code)
        return statuses
    monkeypatch.delenv("VERCEL",raising=False)
    # Off Vercel the header is one more spoofable header: a single budget of five demos.
    assert burst(lambda i:f"203.0.113.{i+1}")==[303]*5+[429]
    monkeypatch.setenv("VERCEL","1")
    # On Vercel the platform sets it to the visitor's address, so each visitor has a separate budget...
    assert burst(lambda i:f"203.0.113.{i+101}")==[303]*6
    # ...but a repeated address, or a first hop followed by spoofed extras, is still throttled.
    assert burst(lambda i:"203.0.113.250, 198.51.100.%d"%i)==[303]*5+[429]
    # A malformed value falls back to the connection address, whose budget is already spent.
    assert burst(lambda i:"<script>",1)==[429]
