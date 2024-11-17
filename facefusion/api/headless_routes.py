import logging
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from typing import List
import shutil
import subprocess
import os
import traceback

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('facefusion_api.log')
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# 在app初始化时创建必要的目录
TEMP_DIR = "temp"
JOBS_DIR = os.path.join(TEMP_DIR, "jobs")

try:
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
        logger.info(f"创建临时目录: {TEMP_DIR}")
    if not os.path.exists(JOBS_DIR):
        os.makedirs(JOBS_DIR)
        logger.info(f"创建作业目录: {JOBS_DIR}")
except Exception as e:
    logger.error(f"创建目录失败: {str(e)}")
    logger.error(traceback.format_exc())

def cleanup_files(*files):
    for file in files:
        try:
            if os.path.exists(file):
                os.remove(file)
                logger.info(f"清理文件: {file}")
        except Exception as e:
            logger.error(f"清理文件失败 {file}: {str(e)}")
            logger.error(traceback.format_exc())

def run_command(target: str, sources: List[str], output_file_path: str, output_file_name: str):
    command = [
        'python', 'facefusion.py',
        'headless-run',
        '-j', JOBS_DIR,
        '-t', target,
        '-o', output_file_path,
    ]

    for source in sources:
        command.extend(['-s', source])
        
    logger.info(f"执行命令: {' '.join(command)}")
    
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"命令执行成功，返回码：{result.returncode}")
        logger.info(f"命令输出：\n{result.stdout}")
        
        if not os.path.exists(output_file_path):
            error_msg = f"输出文件未生成: {output_file_path}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
            
        return FileResponse(output_file_path, filename=output_file_name)
        
    except subprocess.CalledProcessError as e:
        logger.error(f"命令执行失败，返回码：{e.returncode}")
        logger.error(f"错误输出：\n{e.stderr}")
        logger.error(f"标准输出：\n{e.stdout}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail={
                "message": "处理失败",
                "error": str(e),
                "stderr": e.stderr,
                "stdout": e.stdout
            }
        )

@app.post("/process-files")
async def process_files(target: UploadFile = File(...), sources: List[UploadFile] = File(...)):
    target_path = None
    source_paths = []
    output_file_path = None
    
    try:
        logger.info(f"接收到新的处理请求 - 目标文件: {target.filename}, 源文件数量: {len(sources)}")
        
        # 保存目标文件
        target_path = os.path.join(TEMP_DIR, target.filename)
        with open(target_path, "wb") as f:
            shutil.copyfileobj(target.file, f)
        logger.info(f"目标文件已保存: {target_path}")

        # 保存源文件
        for source in sources:
            source_path = os.path.join(TEMP_DIR, source.filename)
            with open(source_path, "wb") as f:
                shutil.copyfileobj(source.file, f)
            source_paths.append(source_path)
            logger.info(f"源文件已保存: {source_path}")

        # 设置输出文件路径
        output_file_path = os.path.join(TEMP_DIR, f"output_{target.filename}")
        logger.info(f"输出文件路径: {output_file_path}")
        
        # 调用 run_command
        response = run_command(target_path, source_paths, output_file_path, f"output_{target.filename}")
        
        # 确保文件存在后再返回
        if os.path.exists(output_file_path):
            return response
        else:
            raise HTTPException(status_code=500, detail="处理后的文件不存在")
            
    except Exception as e:
        error_detail = {
            "message": str(e),
            "traceback": traceback.format_exc()
        }
        logger.error("处理请求时发生错误:")
        logger.error(error_detail)
        raise HTTPException(status_code=500, detail=error_detail)
    finally:
        # 等待一段时间后再清理文件
        try:
            if response and os.path.exists(output_file_path):
                # 只清理源文件和目标文件，保留输出文件
                cleanup_files(target_path, *source_paths)
            else:
                # 如果处理失败，清理所有文件
                cleanup_files(target_path, *source_paths, output_file_path)
        except Exception as e:
            logger.error(f"清理文件时发生错误: {str(e)}")