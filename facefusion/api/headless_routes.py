from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from typing import Optional, List, Union
from enum import Enum
from pydantic import BaseModel, HttpUrl
import shutil
from pathlib import Path
import aiohttp
import asyncio
import os
import traceback
import logging

from facefusion import process_manager, state_manager
from facefusion.core import process_headless
from facefusion.typing import Args
from facefusion.temp_helper import clear_temp_directory

# 创建临时和输出目录
TEMP_DIR = Path("temp")
OUTPUT_DIR = Path("output") 
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

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

def get_output_path(filename: str) -> str:
    """生成输出文件路径"""
    # 生成唯一的输出文件名
    name, ext = os.path.splitext(filename)
    timestamp = asyncio.get_event_loop().time()
    output_filename = f"{name}_{int(timestamp)}{ext}"
    return str(OUTPUT_DIR / output_filename)

app = FastAPI()

logger = logging.getLogger(__name__)

def cleanup_files(*paths: Path) -> None:
    """清理临时文件"""
    try:
        logger.debug("开始清理临时文件")
        process_manager.end()
        
        target_path = state_manager.get_item('target_path')
        if target_path:
            logger.debug(f"清理目标文件临时目录: {target_path}")
            clear_temp_directory(target_path)
            
        for path in paths:
            if path and path.exists():
                logger.debug(f"删除临时文件: {path}")
                path.unlink()
                
    except Exception as e:
        logger.error(f"清理文件失败: {str(e)}\n{traceback.format_exc()}")

@app.post("/headless/url")
async def headless_process_url(request: HeadlessUrlRequest):
    target_path = None
    source_path = None
    try:
        logger.info(f"处理URL请求: target={request.target_url}, source={request.source_url}")
        
        # 下载目标文件
        target_path = await download_file(request.target_url)
        
        # 下载源文件(如果有)
        if request.source_url:
            source_path = await download_file(request.source_url)
            
        # 生成输出路径
        output_path = get_output_path(target_path.name)
            
        # 构建参数
        args: Args = {
            'processors': request.processors,
            'target_path': str(target_path),
            'output_path': output_path
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
            
        return {
            "message": "处理成功", 
            "output_path": output_path,
            "output_filename": os.path.basename(output_path)
        }
        
    except Exception as e:
        error_msg = f"处理失败: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
        
    finally:
        try:
            cleanup_files(source_path, target_path)
        except Exception as e:
            logger.error(f"清理文件失败: {str(e)}\n{traceback.format_exc()}")

@app.post("/headless/upload") 
async def headless_process_upload(
    processors: List[ProcessorType],
    target: UploadFile = File(...),
    source: Optional[UploadFile] = None,
    trim_frame_start: Optional[int] = Form(None),
    trim_frame_end: Optional[int] = Form(None)
):
    target_path = None
    source_path = None
    try:
        # 保存目标文件
        target_path = TEMP_DIR / target.filename
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)
            
        # 保存源文件(如果有)
        if source:
            source_path = TEMP_DIR / source.filename
            with open(source_path, "wb") as f:
                shutil.copyfileobj(source.file, f)
                
        # 生成输出路径
        output_path = get_output_path(target.filename)
                
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
            
        return {
            "message": "处理成功", 
            "output_path": output_path,
            "output_filename": os.path.basename(output_path)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # 清理临时文件
        cleanup_files(source_path, target_path)