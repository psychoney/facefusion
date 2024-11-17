from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from typing import List
import shutil
import subprocess
import os

app = FastAPI()

# 现有的 run_command 函数
def run_command(target: str, sources: List[str], output_file_path: str, output_file_name: str):
    command = [
        'python', 'facefusion.py',
        '--headless',
        '--execution-providers', 'cpu', 'cuda',
        '-t', target,
        '-o', output_file_path
    ]

    for source in sources:
        command.append('-s')
        command.append(source)
    print("执行命令: ", command)
    try:
        result = subprocess.run(command, check=True)
        print(f"命令执行成功，返回码：{result.returncode}")
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败，返回码：{e.returncode}")
        raise HTTPException(status_code=500, detail="处理失败")
    
    return FileResponse(output_file_path, filename=output_file_name)

# 新的 API 路由
@app.post("/process-files")
async def process_files(target: UploadFile = File(...), sources: List[UploadFile] = File(...)):
    # 保存目标文件
    target_path = f"temp/{target.filename}"
    with open(target_path, "wb") as f:
        shutil.copyfileobj(target.file, f)

    # 保存源文件
    source_paths = []
    for source in sources:
        source_path = f"temp/{source.filename}"
        with open(source_path, "wb") as f:
            shutil.copyfileobj(source.file, f)
        source_paths.append(source_path)

    # 设置输出文件路径
    output_file_path = f"temp/output_{target.filename}"
    
    # 调用 run_command
    return run_command(target_path, source_paths, output_file_path, f"output_{target.filename}")