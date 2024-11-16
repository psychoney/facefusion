from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
import shutil
import os
from typing import List
from pathlib import Path
import traceback

from facefusion.uis.components.face_swapper_options import update_face_swapper_pixel_boost
from facefusion.uis.components.face_selector import update_face_selector_mode
from facefusion.processors.modules.face_swapper import process_image, process_video
from facefusion.core import conditional_append_reference_faces
from facefusion.content_analyser import analyse_frame
from facefusion.vision import read_static_image, read_static_images, detect_faces
from facefusion.face_store import get_reference_faces
from facefusion.face_analyser import get_one_face, get_many_faces

app = FastAPI(title="FaceFusion API")

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

@app.post("/swap-face/image")
async def swap_face_image(
    source: UploadFile = File(...),
    target: UploadFile = File(...),
):
    try:
        # 创建临时文件保存上传的图片
        source_path = TEMP_DIR / source.filename
        target_path = TEMP_DIR / target.filename 
        output_path = TEMP_DIR / f"output_{target.filename}"
        
        # 保存上传的文件
        with open(source_path, "wb") as f:
            shutil.copyfileobj(source.file, f)
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)

        # 验证源图片中是否包含人脸
        source_frame = read_static_image(str(source_path))
        if source_frame is None:
            raise HTTPException(status_code=400, detail="无法读取源图片")
            
        source_faces = get_many_faces([source_frame])
        if not source_faces:
            raise HTTPException(status_code=400, detail="在源图片中未检测到人脸")

        # 验证目标图片中是否包含人脸
        target_frame = read_static_image(str(target_path))
        if target_frame is None:
            raise HTTPException(status_code=400, detail="无法读取目标图片")
            
        target_faces = get_many_faces([target_frame])
        if not target_faces:
            raise HTTPException(status_code=400, detail="在目标图片中未检测到人脸")

        # 设置换脸参数
        update_face_swapper_pixel_boost("2")
        update_face_selector_mode("one")
        
        try:
            # 处理图片换脸
            process_image([str(source_path)], str(target_path), str(output_path))
            
            if not output_path.exists():
                raise HTTPException(status_code=500, detail="处理后的图片未生成")
                
            return FileResponse(
                output_path,
                media_type="image/jpeg",
                filename=f"output_{target.filename}"
            )
            
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"换脸处理失败: {str(e)}")
        
    except HTTPException as he:
        raise he
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 清理临时文件
        for file in [source_path, target_path, output_path]:
            if file.exists():
                file.unlink()

@app.post("/swap-face/video") 
async def swap_face_video(
    source: UploadFile = File(...),
    target: UploadFile = File(...),
):
    try:
        # 创建临时文件保存上传的文件
        source_path = TEMP_DIR / source.filename
        target_path = TEMP_DIR / target.filename
        output_path = TEMP_DIR / f"output_{target.filename}"
        temp_frames_dir = TEMP_DIR / "frames"
        temp_frames_dir.mkdir(exist_ok=True)
        
        # 保存上传的文件
        with open(source_path, "wb") as f:
            shutil.copyfileobj(source.file, f)
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)

        # 设置换脸参数  
        update_face_swapper_pixel_boost("2")
        update_face_selector_mode("one")

        # 提取视频帧
        subprocess.run([
            "ffmpeg", "-i", str(target_path),
            str(temp_frames_dir / "frame_%d.jpg")
        ])
        
        # 获取所有帧文件路径
        frame_paths = sorted(list(temp_frames_dir.glob("*.jpg")))
        
        # 处理视频换脸
        process_video([str(source_path)], [str(p) for p in frame_paths])
        
        # 合成视频
        subprocess.run([
            "ffmpeg", "-i", str(temp_frames_dir / "frame_%d.jpg"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(output_path)
        ])
        
        # 返回处理后的视频
        return FileResponse(output_path)
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 清理临时文件
        for file in [source_path, target_path, output_path]:
            if file.exists():
                file.unlink()
        if temp_frames_dir.exists():
            shutil.rmtree(temp_frames_dir) 