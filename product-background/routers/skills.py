import uuid
import shutil
import zipfile
import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from schemas.skill import SkillCreate, SkillUpdate, SkillResponse
from models.skill import Skill

router = APIRouter(prefix="/api/skills", tags=["Skills"])

# 技能文件夹存储目录
SKILLS_STORAGE_DIR = Path(__file__).parent.parent / "skills_storage"
SKILLS_STORAGE_DIR.mkdir(exist_ok=True)


@router.get("", response_model=List[SkillResponse])
async def get_skills(db: Session = Depends(get_db)):
    """获取所有技能"""
    skills = db.query(Skill).order_by(Skill.created_at.desc()).all()
    return skills


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, db: Session = Depends(get_db)):
    """获取单个技能"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return skill


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(skill_data: SkillCreate, db: Session = Depends(get_db)):
    """
    手动创建技能

    如果提供了 code 字段，会自动创建文件夹和脚本文件
    如果没有提供 code，会创建一个 AI 型技能（SKILL.md）
    """
    skill_id = str(uuid.uuid4())
    skill_folder = SKILLS_STORAGE_DIR / skill_id
    skill_folder.mkdir(parents=True, exist_ok=True)

    entry_script = skill_data.entry_script or "main.py"

    # 如果提供了代码，创建 Python 脚本
    if skill_data.code:
        script_path = skill_folder / entry_script
        script_path.write_text(skill_data.code, encoding="utf-8")
    else:
        # 没有提供代码，创建 AI 型技能（SKILL.md）
        skill_md_content = f"""# {skill_data.name}

## 技能说明
{skill_data.description or '这是一个 AI 驱动的技能。'}

## 功能
根据用户输入的需求，使用 AI 智能处理并生成结果。

## 使用方式
直接描述你的需求，AI 会根据技能的定位来处理你的请求。

## 标签
{', '.join(skill_data.tags) if skill_data.tags else '通用'}

---
*此技能由 AI Skills Platform 自动创建*
"""
        skill_md_path = skill_folder / "SKILL.md"
        skill_md_path.write_text(skill_md_content, encoding="utf-8")
        entry_script = None  # AI 型技能没有入口脚本

    # 处理 output_config
    output_config_dict = None
    if skill_data.output_config:
        output_config_dict = skill_data.output_config.model_dump()

    # 写入 config.json
    config = {
        "name": skill_data.name,
        "description": skill_data.description,
        "icon": skill_data.icon,
        "tags": skill_data.tags or [],
        "author": skill_data.author,
        "version": skill_data.version or "1.0.0",
        "entry_script": entry_script,
        "type": "python" if skill_data.code else "ai_prompt",
        "output_config": output_config_dict  # 输出配置
    }
    config_path = skill_folder / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    skill = Skill(
        id=skill_id,
        name=skill_data.name,
        description=skill_data.description,
        icon=skill_data.icon,
        tags=skill_data.tags,
        folder_path=skill_id,  # 始终设置 folder_path
        entry_script=entry_script,
        author=skill_data.author,
        version=skill_data.version,
        interactions=([i.model_dump() for i in skill_data.interactions]
                     if skill_data.interactions else []),
        output_config=output_config_dict  # 输出配置
    )

    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.post("/upload", response_model=SkillResponse, status_code=201)
async def upload_skill(
    file: UploadFile = File(..., description="技能文件夹的 ZIP 压缩包"),
    name: str = Form(..., description="技能名称"),
    description: Optional[str] = Form(None, description="技能描述"),
    icon: Optional[str] = Form("⚡", description="图标"),
    tags: Optional[str] = Form(None, description="标签，JSON 数组格式"),
    entry_script: Optional[str] = Form("main.py", description="入口脚本"),
    author: Optional[str] = Form(None, description="作者"),
    version: Optional[str] = Form("1.0.0", description="版本"),
    db: Session = Depends(get_db)
):
    """
    上传技能文件夹（ZIP 压缩包）

    文件夹结构示例：
    ```
    my-skill/
    ├── main.py          # 入口脚本
    ├── requirements.txt # 依赖（可选）
    └── config.json      # 配置（可选）
    ```
    """
    # 验证文件类型
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传 ZIP 压缩包")

    # 生成 UUID
    skill_id = str(uuid.uuid4())
    skill_folder = SKILLS_STORAGE_DIR / skill_id

    try:
        # 保存并解压 ZIP 文件
        temp_zip = SKILLS_STORAGE_DIR / f"temp_{skill_id}.zip"
        content = await file.read()
        temp_zip.write_bytes(content)

        # 解压到技能文件夹
        skill_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(skill_folder)

        # 删除临时 ZIP
        temp_zip.unlink()

        # 检查是否有嵌套文件夹（常见的 ZIP 打包方式）
        items = list(skill_folder.iterdir())
        if len(items) == 1 and items[0].is_dir():
            # 将内容移动到上层
            nested_folder = items[0]
            for item in nested_folder.iterdir():
                shutil.move(str(item), str(skill_folder / item.name))
            nested_folder.rmdir()

        # 解析标签
        tags_list = []
        if tags:
            try:
                tags_list = json.loads(tags)
            except json.JSONDecodeError:
                tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        # 尝试从 config.json 读取额外信息
        config_file = skill_folder / "config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                if not description and "description" in config:
                    description = config["description"]
                if not tags_list and "tags" in config:
                    tags_list = config["tags"]
                if "icon" in config:
                    icon = config["icon"]
                if "author" in config:
                    author = config["author"]
                if "version" in config:
                    version = config["version"]
                if "entry_script" in config:
                    entry_script = config["entry_script"]
            except Exception:
                pass

        # 创建数据库记录
        skill = Skill(
            id=skill_id,
            name=name,
            description=description,
            icon=icon,
            tags=tags_list,
            folder_path=skill_id,  # 相对路径就是 ID
            entry_script=entry_script,
            author=author,
            version=version
        )

        db.add(skill)
        db.commit()
        db.refresh(skill)

        return skill

    except Exception as e:
        # 清理失败的上传
        if skill_folder.exists():
            shutil.rmtree(skill_folder)
        if temp_zip.exists():
            temp_zip.unlink()
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    skill_data: SkillUpdate,
    db: Session = Depends(get_db)
):
    """更新技能基本信息，如果提供 code 则更新脚本文件"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    update_data = skill_data.model_dump(exclude_unset=True)

    # 处理代码更新
    if "code" in update_data and update_data["code"] is not None:
        code = update_data.pop("code")  # 从 update_data 中移除，不存入数据库

        # 确定脚本文件名
        script_name = update_data.get("entry_script") or skill.entry_script or "main.py"

        # 确保文件夹存在
        skill_folder = SKILLS_STORAGE_DIR / skill_id
        if not skill_folder.exists():
            skill_folder.mkdir(parents=True, exist_ok=True)
            skill.folder_path = skill_id

        # 写入脚本文件
        script_path = skill_folder / script_name
        script_path.write_text(code, encoding="utf-8")

        # 更新 config.json
        config_path = skill_folder / "config.json"
        # 获取 output_config
        output_cfg = update_data.get("output_config") or skill.output_config
        if output_cfg and hasattr(output_cfg, 'model_dump'):
            output_cfg = output_cfg.model_dump()
        config = {
            "name": update_data.get("name") or skill.name,
            "description": update_data.get("description") or skill.description,
            "icon": update_data.get("icon") or skill.icon,
            "tags": update_data.get("tags") or skill.tags or [],
            "author": update_data.get("author") or skill.author,
            "version": update_data.get("version") or skill.version or "1.0.0",
            "entry_script": script_name,
            "output_config": output_cfg
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    # 处理 interactions
    if "interactions" in update_data and update_data["interactions"] is not None:
        update_data["interactions"] = [
            i.model_dump() if hasattr(i, 'model_dump') else i
            for i in update_data["interactions"]
        ]

    # 处理 output_config
    if "output_config" in update_data and update_data["output_config"] is not None:
        output_cfg = update_data["output_config"]
        update_data["output_config"] = output_cfg.model_dump() if hasattr(output_cfg, 'model_dump') else output_cfg

    for key, value in update_data.items():
        setattr(skill, key, value)

    db.commit()
    db.refresh(skill)
    return skill


@router.put("/{skill_id}/folder", response_model=SkillResponse)
async def update_skill_folder(
    skill_id: str,
    file: UploadFile = File(..., description="新的技能文件夹 ZIP 压缩包"),
    db: Session = Depends(get_db)
):
    """更新技能文件夹"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="请上传 ZIP 压缩包")

    skill_folder = SKILLS_STORAGE_DIR / skill_id

    try:
        # 删除旧文件夹内容
        if skill_folder.exists():
            shutil.rmtree(skill_folder)

        # 保存并解压新 ZIP
        temp_zip = SKILLS_STORAGE_DIR / f"temp_{skill_id}.zip"
        content = await file.read()
        temp_zip.write_bytes(content)

        skill_folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(skill_folder)

        temp_zip.unlink()

        # 处理嵌套文件夹
        items = list(skill_folder.iterdir())
        if len(items) == 1 and items[0].is_dir():
            nested_folder = items[0]
            for item in nested_folder.iterdir():
                shutil.move(str(item), str(skill_folder / item.name))
            nested_folder.rmdir()

        # 更新 folder_path
        skill.folder_path = skill_id
        db.commit()
        db.refresh(skill)

        return skill

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: str, db: Session = Depends(get_db)):
    """删除技能（同时删除数据库记录和文件夹）"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    # 删除文件夹
    if skill.folder_path:
        skill_folder = SKILLS_STORAGE_DIR / skill.folder_path
        if skill_folder.exists():
            shutil.rmtree(skill_folder)

    # 删除数据库记录
    db.delete(skill)
    db.commit()

    return None


@router.get("/{skill_id}/files")
async def get_skill_files(skill_id: str, db: Session = Depends(get_db)):
    """获取技能文件夹中的文件列表"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    if not skill.folder_path:
        return {"files": []}

    skill_folder = SKILLS_STORAGE_DIR / skill.folder_path
    if not skill_folder.exists():
        return {"files": []}

    files = []
    for item in skill_folder.rglob("*"):
        if item.is_file():
            rel_path = item.relative_to(skill_folder)
            files.append({
                "name": item.name,
                "path": str(rel_path),
                "size": item.stat().st_size
            })

    return {"files": files}


@router.get("/{skill_id}/file/{file_path:path}")
async def get_skill_file_content(
    skill_id: str,
    file_path: str,
    db: Session = Depends(get_db)
):
    """获取技能文件内容"""
    skill = db.query(Skill).filter(Skill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")

    if not skill.folder_path:
        raise HTTPException(status_code=404, detail="技能没有文件夹")

    file_full_path = SKILLS_STORAGE_DIR / skill.folder_path / file_path
    if not file_full_path.exists() or not file_full_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 安全检查：防止路径遍历
    try:
        file_full_path.resolve().relative_to((SKILLS_STORAGE_DIR / skill.folder_path).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="非法路径")

    try:
        content = file_full_path.read_text(encoding="utf-8")
        return {"content": content}
    except UnicodeDecodeError:
        return {"content": None, "binary": True, "size": file_full_path.stat().st_size}
