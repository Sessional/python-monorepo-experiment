from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import lib1

app = FastAPI()


stuff = "things"

templates = Jinja2Templates(directory="templates")

@app.get("/")
def read_root(request: Request):
     return templates.TemplateResponse(request=request, name="template.jinja", context={"first": lib1.hello(), "second": "Hello from app."})
