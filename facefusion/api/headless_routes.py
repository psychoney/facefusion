from fastapi import FastAPI, HTTPException
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel

from facefusion import process_manager, state_manager
from facefusion.core import process_headless
from facefusion.typing import Args

class ProcessorType(str, Enum):
    face_swapper = 'face_swapper'
    face_enhancer = 'face_enhancer' 
    frame_enhancer = 'frame_enhancer'
    face_debugger = 'face_debugger'
    
class HeadlessRequest(BaseModel):
    processors: List[ProcessorType]
    source_path: Optional[str] = None
    target_path: str
    output_path: str
    trim_frame_start: Optional[int] = None 
    trim_frame_end: Optional[int] = None

app = FastAPI()

@app.post("/headless")
async def headless_process(request: HeadlessRequest):
    try:
        # 构建参数字典
        args: Args = {
            'processors': request.processors,
            'target_path': request.target_path,
            'output_path': request.output_path
        }
        
        # 可选参数
        if request.source_path:
            args['source_path'] = request.source_path
            
        if request.trim_frame_start is not None:
            args['trim_frame_start'] = request.trim_frame_start
            
        if request.trim_frame_end is not None:
            args['trim_frame_end'] = request.trim_frame_end
            
        # 调用headless处理
        error_code = process_headless(args)
        
        if error_code != 0:
            raise HTTPException(status_code=500, detail=f"处理失败,错误码:{error_code}")
            
        return {"message": "处理成功", "output_path": request.output_path}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # 清理进程
        process_manager.end() 