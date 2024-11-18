import uvicorn
from facefusion.api.headless_routes import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7880) 