from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()

from routers import lens_router

app = FastAPI(title='LENS API - Content Reviewer & Consistency Auditor', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(lens_router.router)


@app.get('/health')
def health():
    return {
        'status': 'ok',
        'agent': 'LENS',
        'eyebrow': 'CONTENT REVIEWER & CONSISTENCY AUDITOR'
    }


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=8003, reload=True)

