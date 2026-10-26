// Prevent unsaved editor changes from being confused with the reviewed snapshot.
const draft=document.querySelector('[data-draft]');
if(draft){
  draft.addEventListener('input',()=>{
    const status=document.querySelector('[data-draft-status]');
    if(status)status.textContent='You have unsaved changes. Save the draft before reviewing or delivering it.';
    document.querySelectorAll('[data-deliver]').forEach(button=>button.disabled=true);
    document.querySelectorAll('[data-review]').forEach(link=>{link.setAttribute('aria-disabled','true');link.addEventListener('click',event=>event.preventDefault());});
  });
}
