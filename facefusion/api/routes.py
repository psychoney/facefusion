from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import shutil
from pathlib import Path
import traceback

from facefusion import state_manager, process_manager
from facefusion.core import conditional_process
from facefusion.temp_helper import clear_temp_directory
from facefusion.uis.components.face_swapper_options import update_face_swapper_pixel_boost
from facefusion.uis.components.face_selector import update_face_selector_mode

app = FastAPI()

TEMP_DIR = Path("temp")
TEMP_DIR.mkdir(exist_ok=True)

@app.post("/process")
async def process_media(
    source: UploadFile = File(...),
    target: UploadFile = File(...),
):
    try:
        # 保存上传的文件
        source_path = TEMP_DIR / source.filename
        target_path = TEMP_DIR / target.filename
        output_path = TEMP_DIR / f"output_{target.filename}"
        
        with open(source_path, "wb") as f:
            shutil.copyfileobj(source.file, f)
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)

        # 设置state manager
        state_manager.set_item('source_paths', [str(source_path)])
        state_manager.set_item('target_path', str(target_path))
        state_manager.set_item('output_path', str(output_path))
        
        # 设置处理参数
        state_manager.set_item('processors', ['face_swapper'])  # 添加这行
        update_face_swapper_pixel_boost("2") 
        update_face_selector_mode("one")

        # 处理媒体文件
        error_code = conditional_process()
        
        if error_code != 0:
            raise HTTPException(status_code=500, detail=f"处理失败,错误码:{error_code}")
            
        if not output_path.exists():
            raise HTTPException(status_code=500, detail="输出文件未生成")
            
        return FileResponse(
            output_path,
            filename=f"output_{target.filename}"
        )
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # 清理临时文件
        process_manager.end()
        if state_manager.get_item('target_path'):
            clear_temp_directory(state_manager.get_item('target_path'))
        for file in [source_path, target_path, output_path]:
            if file.exists():
                file.unlink()