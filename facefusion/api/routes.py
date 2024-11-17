from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from typing import Optional
from enum import Enum
from fastapi.responses import FileResponse
import shutil
from pathlib import Path
import traceback

from facefusion import state_manager, process_manager
from facefusion.core import conditional_process
from facefusion.temp_helper import clear_temp_directory
from facefusion.uis.components.face_swapper_options import update_face_swapper_pixel_boost
from facefusion.uis.components.face_selector import update_face_selector_mode
from facefusion.face_detector import pre_check as detector_pre_check
from facefusion.face_recognizer import pre_check as recognizer_pre_check
from facefusion.face_landmarker import pre_check as landmarker_pre_check

app = FastAPI()

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

class FaceDetectorModel(str, Enum):
    retinaface = 'retinaface'
    yunet = 'yunet'
    
class FaceRecognizerModel(str, Enum):
    arcface = 'arcface_inswapper'
    buffalo = 'buffalo_l'

@app.post("/process")
async def process_media(
    source: UploadFile = File(...),
    target: UploadFile = File(...),
    face_detector_model: Optional[FaceDetectorModel] = None,
    face_recognizer_model: Optional[FaceRecognizerModel] = None,
):
    source_path = TEMP_DIR / source.filename
    target_path = TEMP_DIR / target.filename
    output_path = TEMP_DIR / f"output_{target.filename}"
    
    try:
        # 保存上传的文件
        with open(source_path, "wb") as f:
            shutil.copyfileobj(source.file, f)
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)

        # 设置基本参数
        state_manager.set_item('source_paths', [str(source_path)])
        state_manager.set_item('target_path', str(target_path))
        state_manager.set_item('output_path', str(output_path))
        
        # 设置处理器
        state_manager.set_item('processors', ['face_swapper'])
        
        # 根据文件类型自动设置其他参数
        if face_detector_model:
            state_manager.set_item('face_detector_model', face_detector_model)
            
        if face_recognizer_model:
            state_manager.set_item('face_recognizer_model', face_recognizer_model)
            
        # 其他参数使用默认值
        update_default_settings()
        
        # 处理媒体文件
        error_code = conditional_process()
        
        if error_code != 0:
            raise HTTPException(status_code=500, detail=f"处理失败,错误码:{error_code}")
            
        return FileResponse(output_path, filename=f"output_{target.filename}")
        
    finally:
        cleanup_files(source_path, target_path, output_path)

def update_default_settings():
    """更新默认设置，参考 gradio 组件的默认值"""
    # 设置执行提供程序
    state_manager.set_item('execution_providers', ['cpu'])
    
    # 参考 face_detector.py 的设置
    state_manager.set_item('face_detector_model', 'retinaface')
    state_manager.set_item('face_detector_size', '640x640')
    state_manager.set_item('face_detector_score', 0.5)
    state_manager.set_item('face_detector_angles', [0])
    
    # 参考 face_landmarker.py 的设置
    state_manager.set_item('face_landmarker_model', '2dfan4')
    state_manager.set_item('face_landmarker_score', 0.5)
    
    # 参考 face_selector.py 的设置
    state_manager.set_item('face_selector_mode', 'one')
    state_manager.set_item('face_selector_order', 'left-right')
    state_manager.set_item('reference_face_position', 0)
    state_manager.set_item('reference_face_distance', 0.6)
    
    # 参考 face_masker.py 的设置
    state_manager.set_item('face_mask_types', ['box'])
    state_manager.set_item('face_mask_blur', 0.3)
    state_manager.set_item('face_mask_padding', [0, 0, 0, 0])
    state_manager.set_item('face_mask_regions', ['skin'])
    
    # 参考 frame_extraction.py 的设置
    state_manager.set_item('temp_frame_format', 'jpg')
    state_manager.set_item('keep_temp', False)
    
    # 参考 output_options.py 的设置
    state_manager.set_item('output_image_quality', 90)
    state_manager.set_item('output_image_resolution', 'source')
    state_manager.set_item('output_video_encoder', 'libx264')
    state_manager.set_item('output_video_quality', 90)
    state_manager.set_item('output_video_resolution', 'source')
    state_manager.set_item('output_video_fps', 'source')

def cleanup_files(source_path: Path, target_path: Path, output_path: Path):
    # 清理临时文件
    process_manager.end()
    if state_manager.get_item('target_path'):
        clear_temp_directory(state_manager.get_item('target_path'))
    for file in [source_path, target_path, output_path]:
        if file.exists():
            file.unlink()