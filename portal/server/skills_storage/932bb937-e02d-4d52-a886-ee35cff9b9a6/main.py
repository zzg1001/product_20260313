"""
Image Enhancer - 图片增强技能

使用 PIL/Pillow 对图片进行增强处理：
- 提高清晰度
- 锐化
- 调整对比度
- 降噪
- 放大（超分辨率）
"""

from pathlib import Path
from datetime import datetime
import json


def main(params: dict):
    """
    图片增强主函数

    params:
        file_path: 输入图片路径
        file_paths: 多个图片路径列表
        enhance_level: 增强级别 (light, medium, strong)
        upscale: 放大倍数 (1, 2, 4)
        output_format: 输出格式 (png, jpg, webp)
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return {
            "success": False,
            "error": "需要安装 Pillow 库: pip install Pillow",
            "_no_output_file": True
        }

    # 获取参数
    file_paths = params.get('file_paths', [])
    file_path = params.get('file_path', '')
    if file_path and file_path not in file_paths:
        file_paths.append(file_path)

    if not file_paths:
        return {
            "success": False,
            "error": "请上传需要增强的图片",
            "_no_output_file": True
        }

    enhance_level = params.get('enhance_level', 'medium')
    upscale = int(params.get('upscale', 1))
    output_format = params.get('output_format', 'png').lower()

    # 增强参数配置
    levels = {
        'light': {'sharpness': 1.2, 'contrast': 1.1, 'color': 1.05},
        'medium': {'sharpness': 1.5, 'contrast': 1.2, 'color': 1.1},
        'strong': {'sharpness': 2.0, 'contrast': 1.4, 'color': 1.2}
    }
    config = levels.get(enhance_level, levels['medium'])

    # 输出目录
    outputs_dir = Path(__file__).parent.parent.parent / "outputs"
    outputs_dir.mkdir(exist_ok=True)

    results = []

    for fp in file_paths:
        path = Path(fp)
        if not path.exists():
            results.append({"file": path.name, "error": "文件不存在"})
            continue

        # 检查是否是图片
        if path.suffix.lower() not in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']:
            results.append({"file": path.name, "error": "不是支持的图片格式"})
            continue

        try:
            # 打开图片
            img = Image.open(path)
            original_size = img.size
            original_mode = img.mode

            # 转换为 RGB（如果需要）
            if img.mode in ('RGBA', 'LA', 'P'):
                # 保持透明通道
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background = Image.new('RGBA', img.size, (255, 255, 255, 0))
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[3])
                else:
                    background.paste(img)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 1. 放大（如果需要）
            if upscale > 1:
                new_size = (img.width * upscale, img.height * upscale)
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            # 2. 锐化
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(config['sharpness'])

            # 3. 对比度
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(config['contrast'])

            # 4. 色彩饱和度
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(config['color'])

            # 5. 轻微降噪（使用中值滤波）
            if enhance_level == 'strong':
                img = img.filter(ImageFilter.MedianFilter(size=3))

            # 6. 边缘增强
            img = img.filter(ImageFilter.EDGE_ENHANCE)

            # 生成输出文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"{path.stem}_enhanced_{timestamp}.{output_format}"
            output_path = outputs_dir / output_name

            # 保存
            save_kwargs = {}
            if output_format in ['jpg', 'jpeg']:
                save_kwargs['quality'] = 95
                save_kwargs['optimize'] = True
                if img.mode == 'RGBA':
                    img = img.convert('RGB')
            elif output_format == 'png':
                save_kwargs['optimize'] = True
            elif output_format == 'webp':
                save_kwargs['quality'] = 95

            img.save(output_path, **save_kwargs)

            results.append({
                "file": path.name,
                "success": True,
                "original_size": f"{original_size[0]}x{original_size[1]}",
                "new_size": f"{img.width}x{img.height}",
                "output": output_name,
                "url": f"/outputs/{output_name}",
                "enhancements": [
                    f"锐化: {config['sharpness']}x",
                    f"对比度: {config['contrast']}x",
                    f"饱和度: {config['color']}x",
                    f"放大: {upscale}x" if upscale > 1 else None,
                    "边缘增强",
                    "降噪" if enhance_level == 'strong' else None
                ]
            })

        except Exception as e:
            results.append({"file": path.name, "error": str(e)})

    # 返回结果
    if len(results) == 1 and results[0].get('success'):
        # 单个文件成功，直接返回文件
        r = results[0]
        output_path = outputs_dir / r['output']
        return {
            "message": f"图片增强完成: {r['original_size']} → {r['new_size']}",
            "enhancements": [e for e in r['enhancements'] if e],
            "_output_file": {
                "path": str(output_path),
                "type": output_format,
                "name": r['output'],
                "url": r['url'],
                "size": output_path.stat().st_size
            }
        }
    else:
        # 多个文件或有错误，返回汇总
        return {
            "success": all(r.get('success') for r in results),
            "results": results,
            "summary": f"处理了 {len(results)} 个文件，成功 {sum(1 for r in results if r.get('success'))} 个"
        }


if __name__ == "__main__":
    # 测试
    result = main({
        "file_path": "test.png",
        "enhance_level": "medium"
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
