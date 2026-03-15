"""JSON 转 Excel 技能"""
import json
from pathlib import Path

def main(params):
    """将 JSON 文件转换为 Excel"""
    import pandas as pd

    files = params.get('files', [])
    file_path = params.get('file_path', '')

    input_file = files[0] if files else file_path
    if not input_file:
        return {'status': 'error', 'message': '请上传 JSON 文件'}

    try:
        # 读取 JSON（尝试多种编码）
        data = None
        for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']:
            try:
                with open(input_file, 'r', encoding=encoding) as f:
                    data = json.load(f)
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

        if data is None:
            return {'status': 'error', 'message': '无法读取 JSON 文件，请检查文件编码'}

        # 转换为 DataFrame
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            # 如果是单个对象，转换为单行
            df = pd.DataFrame([data])
        else:
            return {'status': 'error', 'message': 'JSON 格式不支持，需要数组或对象'}

        # 生成输出文件
        output_name = generate_unique_filename('output', 'xlsx')
        output_path = OUTPUTS_DIR / output_name

        # 写入 Excel
        df.to_excel(output_path, index=False, engine='openpyxl')

        return {
            'status': 'success',
            'message': f'转换完成，共 {len(df)} 行数据',
            'content': f'已将 JSON 转换为 Excel，共 {len(df)} 行',
            '_output_file': {
                'path': str(output_path),
                'type': 'excel',
                'name': output_name,
                'url': f'/outputs/{output_name}'
            }
        }
    except json.JSONDecodeError as e:
        return {'status': 'error', 'message': f'JSON 解析错误: {e}'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
