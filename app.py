from followdesk import create_app

app=create_app()

if __name__=="__main__":
    import os
    app.run(host="127.0.0.1",port=int(os.environ.get("FOLLOWDESK_PORT","5059")),debug=False)
