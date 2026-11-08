"""Prepare a browser handoff only. No generation, account API or media download."""
import base64,json,time,uuid
from pydantic import BaseModel,Field,field_validator
from backend.models.schema import MusicBrief

class SunoDraftRequest(BaseModel):
    account_email: str=Field(min_length=3,max_length=254)
    prompt_index: int=Field(default=0,ge=0,le=7)
    @field_validator('account_email')
    @classmethod
    def email(cls,value):
        import re
        value=value.strip().lower()
        if not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+',value):
            raise ValueError('Enter the email shown in your Suno account settings')
        return value

def prepare_draft(root,config,request:SunoDraftRequest):
    brief=MusicBrief.model_validate_json((root/'music_brief.json').read_text())
    if request.prompt_index>=len(brief.prompts): raise ValueError('Choose an existing Suno prompt')
    styles='Instrumental only, no vocals. '+brief.prompts[request.prompt_index].strip()
    if len(styles)>1000: raise ValueError('Shorten this prompt to fit the 1000-character Suno Styles field')
    draft={'version':1,'id':uuid.uuid4().hex,'account_email':request.account_email,
           'title':config['name'].strip(),'styles':styles,'instrumental':True,
           'mode':'prepare_only','created':int(time.time())}
    raw=json.dumps(draft,ensure_ascii=False,separators=(',',':')).encode()
    encoded=base64.urlsafe_b64encode(raw).decode().rstrip('=')
    (root/'suno_draft.json').write_text(json.dumps(draft,ensure_ascii=False,indent=2))
    return {'draft':draft,'url':'https://suno.com/create#liminal-draft='+encoded,
            'state':'Browser preparation requested','note':'Requires the Liminal Suno Prep Chrome extension. Check its Prepared banner before clicking Create yourself.'}
