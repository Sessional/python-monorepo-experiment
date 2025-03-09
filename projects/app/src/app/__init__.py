from fastapi import FastAPI
import lib1

app = FastAPI()


stuff = "things"

@app.get("/")
def read_root():
     return {lib1.hello(): "Hello from app."}
