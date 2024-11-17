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
from facefusion.temp_helper import get_temp_directory_path
from facefusion.jobs import job_manager

# 创建必要的目录
TEMP_DIR = Path("temp")
OUTPUT_DIR = Path("output")
JOBS_DIR = Path("jobs")

for directory in [TEMP_DIR, OUTPUT_DIR, JOBS_DIR]:
    directory.mkdir(exist_ok=True)
    
# 初始化jobs目录
job_manager.init_jobs(str(JOBS_DIR))

# 设置jobs目录路径
state_manager.set_item('jobs_directory_path', str(JOBS_DIR))

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

def setup_process_state(args: Args) -> None:
    """设置处理状态"""
    # 先应用默认设置
    init_api_default_settings()
    
    # 再应用自定义参数
    processors = args.get('processors')
    if isinstance(processors, list):
        state_manager.set_item('processors', [p.value if isinstance(p, ProcessorType) else p for p in processors])
    
    # 设置路径
    state_manager.set_item('source_paths', [args.get('source_path')] if args.get('source_path') else [])
    state_manager.set_item('target_path', args['target_path'])
    state_manager.set_item('output_path', args['output_path'])
    
    # 应用其他可选参数
    for key in ['face_enhancer_model', 'face_enhancer_blend', 
                'output_video_quality', 'output_video_fps', 'skip_audio']:
        if args.get(key) is not None:
            state_manager.set_item(key, args[key])

def init_api_default_settings():
    """初始化API默认设置"""
    # 基础设置
    state_manager.set_item('execution_providers', ['cpu'])
    state_manager.set_item('processors', ['face_swapper'])
    
    # 人脸检测相关
    state_manager.set_item('face_detector_model', 'retinaface')
    state_manager.set_item('face_detector_size', '640x640')
    state_manager.set_item('face_detector_score', 0.5)
    state_manager.set_item('face_detector_angles', [0])
    
    # 人脸标记相关
    state_manager.set_item('face_landmarker_model', '2dfan4')
    state_manager.set_item('face_landmarker_score', 0.5)
    
    # 人脸选择相关
    state_manager.set_item('face_selector_mode', 'reference')
    state_manager.set_item('face_selector_order', 'large-small')
    state_manager.set_item('reference_face_position', 0)
    state_manager.set_item('reference_face_distance', 0.6)
    
    # 人脸增强相关
    state_manager.set_item('face_enhancer_model', 'gfpgan_1.4')
    state_manager.set_item('face_enhancer_blend', 80)
    
    # 人脸编辑相关
    state_manager.set_item('face_editor_model', 'live_portrait')
    
    # 帧处理相关
    state_manager.set_item('frame_colorizer_model', 'ddcolor')
    state_manager.set_item('frame_colorizer_size', '256x256')
    state_manager.set_item('frame_colorizer_blend', 100)
    
    # 输出相关
    state_manager.set_item('output_image_quality', 90)
    state_manager.set_item('output_image_resolution', 'source')
    state_manager.set_item('output_video_encoder', 'libx264')
    state_manager.set_item('output_video_quality', 80)

def validate_args(args: Args) -> None:
    """验证参数有效性"""
    if args.get('output_video_quality') is not None:
        if not 0 <= args['output_video_quality'] <= 100:
            raise HTTPException(status_code=400, detail="output_video_quality must be between 0 and 100")
            
    if args.get('face_enhancer_blend') is not None:
        if not 0 <= args['face_enhancer_blend'] <= 100:
            raise HTTPException(status_code=400, detail="face_enhancer_blend must be between 0 and 100")

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
            
        setup_process_state(args)
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
            
        setup_process_state(args)
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

@app.on_event("startup")
async def startup_event():
    """API 启动时的初始化事件"""
    init_api_default_settings()