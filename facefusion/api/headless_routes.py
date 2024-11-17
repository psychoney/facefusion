from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from typing import Optional, List, Union
from enum import Enum
from pydantic import BaseModel, HttpUrl
import shutil
from pathlib import Path
import aiohttp
import asyncio
import tempfile

from facefusion import process_manager, state_manager
from facefusion.core import process_headless
from facefusion.typing import Args

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

class ProcessorType(str, Enum):
    face_swapper = 'face_swapper'
    face_enhancer = 'face_enhancer' 
    frame_enhancer = 'frame_enhancer'
    face_debugger = 'face_debugger'
    face_editor = 'face_editor'
    age_modifier = 'age_modifier'
    lip_syncer = 'lip_syncer'
    
class HeadlessUrlRequest(BaseModel):
    processors: List[ProcessorType]
    source_url: Optional[HttpUrl] = None
    target_url: HttpUrl
    output_path: str
    trim_frame_start: Optional[int] = None
    trim_frame_end: Optional[int] = None

async def download_file(url: HttpUrl) -> Path:
    """从URL下载文件到临时目录"""
    async with aiohttp.ClientSession() as session:
        async with session.get(str(url)) as response:
            if response.status != 200:
                raise HTTPException(status_code=400, detail=f"下载文件失败: {url}")
                
            # 获取文件名
            filename = url.path.split('/')[-1]
            file_path = TEMP_DIR / filename
            
            # 保存文件
            with open(file_path, 'wb') as f:
                while True:
                    chunk = await response.content.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
            return file_path

app = FastAPI()

@app.post("/headless/url")
async def headless_process_url(request: HeadlessUrlRequest):
    """通过URL处理媒体文件"""
    try:
        # 下载目标文件
        target_path = await download_file(request.target_url)
        
        # 下载源文件(如果有)
        source_path = None
        if request.source_url:
            source_path = await download_file(request.source_url)
            
        # 构建参数
        args: Args = {
            'processors': request.processors,
            'target_path': str(target_path),
            'output_path': request.output_path
        }
        
        if source_path:
            args['source_path'] = str(source_path)
            
        if request.trim_frame_start is not None:
            args['trim_frame_start'] = request.trim_frame_start
            
        if request.trim_frame_end is not None:
            args['trim_frame_end'] = request.trim_frame_end
            
        # 调用处理
        error_code = process_headless(args)
        
        if error_code != 0:
            raise HTTPException(status_code=500, detail=f"处理失败,错误码:{error_code}")
            
        return {"message": "处理成功", "output_path": request.output_path}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # 清理进程和临时文件
        process_manager.end()

@app.post("/headless/upload")
async def headless_process_upload(
    processors: List[ProcessorType],
    target: UploadFile = File(...),
    source: Optional[UploadFile] = None,
    output_path: str = Form(...),
    trim_frame_start: Optional[int] = Form(None),
    trim_frame_end: Optional[int] = Form(None)
):
    """通过文件上传处理媒体文件"""
    try:
        # 保存目标文件
        target_path = TEMP_DIR / target.filename
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)
            
        # 保存源文件(如果有)
        source_path = None
        if source:
            source_path = TEMP_DIR / source.filename
            with open(source_path, "wb") as f:
                shutil.copyfileobj(source.file, f)
                
        # 构建参数
        args: Args = {
            'processors': processors,
            'target_path': str(target_path),
            'output_path': output_path
        }
        
        if source_path:
            args['source_path'] = str(source_path)
            
        if trim_frame_start is not None:
            args['trim_frame_start'] = trim_frame_start
            
        if trim_frame_end is not None:
            args['trim_frame_end'] = trim_frame_end
            
        # 调用处理
        error_code = process_headless(args)
        
        if error_code != 0:
            raise HTTPException(status_code=500, detail=f"处理失败,错误码:{error_code}")
            
        return {"message": "处理成功", "output_path": output_path}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # 清理进程和临时文件
        process_manager.end()