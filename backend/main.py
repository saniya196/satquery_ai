from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from model_utils import analyze_tif, generate_answer

app = FastAPI(title="SatQuery AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "SatQuery AI backend running"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    contents = await file.read()
    result = analyze_tif(contents)
    return result
@app.post("/query")
async def query(file: UploadFile = File(...), question: str = Form("")):
    contents = await file.read()
    analysis = analyze_tif(contents)
    result = generate_answer(analysis, question)
    return result