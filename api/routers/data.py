# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/data.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import json
from zipfile import BadZipFile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr, model_validator
from api.schemas import CrawlerStartRequest
from typing import Literal
from api.services.data_browser import DATA_TYPES, IMAGE_TYPES, browse_posts
from api.services.data_file_visibility import collection_files, internal_record
from api.services.manual_review import annotations, update_annotation
from api.services.data_trash import move_to_trash, list_trash, restore_file, purge_file

class ImageSettingsPrivateInputRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        if self.path not in {'/data/image-subject/settings', '/api/data/image-subject/settings'} or 'PUT' not in self.methods:
            return original

        async def private_validation(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                # Pydantic validation details may contain the raw input,
                # including an API key submitted with the wrong JSON type.
                raise HTTPException(status_code=422, detail='image_subject_key_invalid') from None

        return private_validation


router = APIRouter(prefix="/data", tags=["data"], route_class=ImageSettingsPrivateInputRoute)

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def data_root() -> Path:
    import config
    configured = getattr(config, 'SAVE_DATA_PATH', '')
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = Path(__file__).parent.parent.parent / root
        return root.resolve()
    return DATA_DIR.resolve()


def resolve_file(file_path: str) -> Path:
    root = data_root()
    path = (root / file_path.replace('\\', '/')).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail='Access denied')
    if internal_record(relative):
        raise HTTPException(status_code=403, detail='Internal records are not collection files')
    if not path.is_file():
        raise HTTPException(status_code=404, detail='File not found')
    return path


class ManualReviewUpdate(BaseModel):
    file: str = Field(min_length=1, max_length=1000)
    post_key: str = Field(min_length=1, max_length=1000)
    kind: Literal['image', 'account', 'post']
    decision: Optional[Literal['qualified', 'unqualified', 'marketing', 'non_marketing']] = None
    image_key: Optional[str] = Field(None, max_length=1000)
    partial: bool = False

    @model_validator(mode='after')
    def validate_decision(self):
        allowed = {'marketing', 'non_marketing'} if self.kind == 'account' else {'qualified', 'unqualified'}
        if self.decision is not None and self.decision not in allowed:
            raise ValueError('Decision does not match review kind')
        if self.kind == 'image' and not self.image_key:
            raise ValueError('Image key is required')
        return self


class DeleteDataFile(BaseModel):
    file: str = Field(min_length=1, max_length=1000)


class ImageSubjectRequest(DeleteDataFile):
    force: bool = False


class ImageSubjectSettingsUpdate(BaseModel):
    provider: Literal['local', 'siliconflow']
    api_key: Optional[SecretStr] = None
    clear_key: bool = False


@router.get('/image-subject/settings')
def get_image_subject_settings():
    from image_subject_settings import public_settings
    return public_settings(data_root())


@router.put('/image-subject/settings')
async def update_image_subject_settings(change: ImageSubjectSettingsUpdate):
    from api.services import crawler_manager
    from api.services.image_subject import image_subject_jobs
    from image_subject import inference_busy
    from image_subject_settings import save_settings
    async with crawler_manager._lock:
        if crawler_manager.status in {'running', 'stopping'} or (crawler_manager.process and crawler_manager.process.poll() is None):
            raise HTTPException(status_code=409, detail='collection_active')
        if image_subject_jobs.running or inference_busy(data_root()):
            raise HTTPException(status_code=409, detail='image_subject_busy')
        try:
            key = change.api_key.get_secret_value() if change.api_key is not None else None
            return save_settings(data_root(), change.provider, key, change.clear_key)
        except (ValueError, OSError) as exc:
            code = str(exc) if str(exc).startswith('image_subject_') else 'image_subject_key_storage_failed'
            raise HTTPException(status_code=422, detail=code) from exc


@router.get('/collection-logs')
def get_collection_logs(file: str):
    from api.services.collection_logs import collection_logs
    path = resolve_file(file)
    try:
        return collection_logs(data_root(), path)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail='collection_logs_read_failed') from exc


@router.get('/image-subject')
def image_subject_status(file: str):
    from api.services.image_subject import image_subject_jobs
    try:
        return image_subject_jobs.status(data_root(), resolve_file(file))
    except (ValueError, OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='image_subject_read_failed') from exc


@router.post('/image-subject')
async def recognize_image_subjects(change: ImageSubjectRequest):
    from api.services import crawler_manager
    from api.services.image_subject import image_subject_jobs
    try:
        return await image_subject_jobs.start(data_root(), resolve_file(change.file), crawler_manager, force=change.force)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='image_subject_read_failed') from exc


class SupplementRequest(BaseModel):
    file: str = Field(min_length=1, max_length=1000)
    target: Optional[int] = Field(None, ge=1, le=10000)
    config: Optional[CrawlerStartRequest] = None
    api_key: Optional[SecretStr] = None
    cookies: Optional[SecretStr] = None


@router.get('/supplement')
def get_supplement_plan(file: str):
    from api.services import crawler_manager
    from api.services.supplement import plan
    try:
        return plan(data_root(), resolve_file(file), crawler_manager)
    except (ValueError, OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='supplement_read_failed') from exc


@router.post('/supplement')
async def supplement_collection(change: SupplementRequest):
    from api.services import crawler_manager
    from api.services.supplement import start_supplement
    try:
        return await start_supplement(data_root(), resolve_file(change.file), crawler_manager,
                                      change.target, change.config, change.api_key, change.cookies)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='supplement_read_failed') from exc


def check_file_mutation_allowed():
    from api.services import crawler_manager
    from api.services.image_subject import image_subject_jobs
    from image_subject import inference_busy
    if crawler_manager.status in {'running', 'stopping'} or image_subject_jobs.running or inference_busy(data_root()):
        raise HTTPException(status_code=409, detail='collection_active')


@router.get('/trash')
def get_trash():
    return {'files': list_trash(data_root())}


@router.post('/trash')
def delete_data_file(change: DeleteDataFile):
    check_file_mutation_allowed()
    try:
        return move_to_trash(data_root(), change.file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='File not found') from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail='Access denied') from exc
    except OSError as exc:
        raise HTTPException(status_code=409, detail='file_in_use') from exc


@router.post('/trash/{entry_id}/restore')
def restore_data_file(entry_id: str):
    check_file_mutation_allowed()
    try:
        return restore_file(data_root(), entry_id)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail='restore_conflict') from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='File not found') from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=403, detail='Access denied') from exc
    except OSError as exc:
        raise HTTPException(status_code=409, detail='file_in_use') from exc


@router.delete('/trash/{entry_id}')
def permanently_delete_data_file(entry_id: str):
    check_file_mutation_allowed()
    try:
        return purge_file(data_root(), entry_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='File not found') from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=403, detail='Access denied') from exc
    except OSError as exc:
        raise HTTPException(status_code=409, detail='file_in_use') from exc


@router.get('/review')
def get_manual_review(file: str):
    path = resolve_file(file)
    if path.suffix.lower() not in DATA_TYPES:
        raise HTTPException(status_code=400, detail='Unsupported data file')
    try:
        return annotations(data_root(), path)
    except (ValueError, OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='Could not read review data; check the collection file and saved annotations.') from exc


@router.patch('/review')
def save_manual_review(change: ManualReviewUpdate):
    path = resolve_file(change.file)
    if path.suffix.lower() not in DATA_TYPES:
        raise HTTPException(status_code=400, detail='Unsupported data file')
    try:
        return update_annotation(data_root(), path, change.post_key, change.kind, change.decision, change.image_key, partial=change.partial)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='Could not save review; previous saved annotations have been preserved.') from exc


@router.post('/review/export')
def export_review_results(change: DeleteDataFile):
    from urllib.parse import quote
    from api.services.review_export import export_review
    check_file_mutation_allowed()
    path = resolve_file(change.file)
    if not path.is_file() or path.suffix.lower() not in DATA_TYPES:
        raise HTTPException(status_code=404, detail='File not found')
    try:
        output, filename, counts = export_review(data_root(), path)
        return Response(output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename),
            'X-Review-Retained': str(counts['retained']), 'X-Review-Images': str(counts['images']),
            'X-Review-Pending': str(counts['pending'])})
    except (OSError, ValueError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='review_export_empty' if str(exc) == 'review_export_empty' else 'review_export_failed') from exc


@router.post('/review/export/jobs')
def prepare_review_export(change: DeleteDataFile):
    from api.services.review_export_jobs import review_export_jobs
    check_file_mutation_allowed()
    path = resolve_file(change.file)
    if path.suffix.lower() not in DATA_TYPES:
        raise HTTPException(status_code=400, detail='Unsupported data file')
    try:
        return review_export_jobs.start(data_root(), path)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail='review_export_failed') from exc


@router.get('/review/export/jobs/{identity}')
def review_export_status(identity: str):
    from api.services.review_export_jobs import review_export_jobs
    try:
        return review_export_jobs.status(data_root(), identity)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get('/review/export/jobs')
def list_review_exports():
    from api.services.review_export_jobs import review_export_jobs
    return {'jobs': review_export_jobs.list(data_root())}


@router.get('/review/export/jobs/{identity}/download')
def download_review_package(identity: str):
    from api.services.review_export_jobs import ReviewPackageResponse
    try:
        root = data_root()
        return ReviewPackageResponse(root, identity)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/review/export/jobs/{identity}')
def cancel_review_export(identity: str):
    from api.services.review_export_jobs import review_export_jobs
    try:
        return review_export_jobs.cancel(data_root(), identity)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/browse')
def browse_data(file: str, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                search: str = Query('', max_length=200), status: str = Query('all', pattern='^(all|matched|review|pending|duplicate|excluded|unfiltered)$')):
    path = resolve_file(file)
    if path.suffix.lower() not in DATA_TYPES:
        raise HTTPException(status_code=400, detail='Unsupported data file')
    try:
        return browse_posts(data_root(), path, offset, limit, search, status)
    except (ValueError, OSError, KeyError, BadZipFile) as exc:
        raise HTTPException(status_code=422, detail='Could not read saved data. Check that collection has finished and the file is intact.') from exc


@router.get('/media/{file_path:path}')
def get_saved_image(file_path: str, request: Request, preview: bool = False):
    path = resolve_file(file_path)
    if path.suffix.lower() not in IMAGE_TYPES or 'media' not in path.relative_to(data_root()).parts:
        raise HTTPException(status_code=403, detail='Only collected images can be viewed here')
    if preview:
        from PIL import Image
        from api.services.media_previews import preview_path
        try:
            cached = preview_path(data_root(), path)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise HTTPException(status_code=422, detail='media_preview_failed') from exc
        etag = '"' + cached.stem + '"'
        headers = {'Cache-Control': 'private, max-age=0, must-revalidate',
                   'X-Content-Type-Options': 'nosniff', 'ETag': etag}
        validators = [value.strip().removeprefix('W/') for value in request.headers.get('if-none-match', '').split(',')]
        if etag in validators or '*' in validators:
            return Response(status_code=304, headers=headers)
        return FileResponse(cached, media_type='image/webp', headers=headers)
    return FileResponse(path, headers={'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'})


def get_file_info(file_path: Path) -> dict:
    """Get file information"""
    stat = file_path.stat()
    record_count = None

    # Try to get record count
    try:
        if file_path.suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    record_count = len(data)
        elif file_path.suffix == ".csv":
            with open(file_path, "r", encoding="utf-8") as f:
                record_count = sum(1 for _ in f) - 1  # Subtract header row
    except Exception:
        pass

    info = {
        "name": file_path.name,
        "path": file_path.relative_to(data_root()).as_posix(),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "record_count": record_count,
        "type": file_path.suffix[1:] if file_path.suffix else "unknown"
    }
    if file_path.name.lower().endswith('_semantic.xlsx'):
        from collection_tasks import find_task, task_files
        main = file_path.with_name(file_path.name[:-len('_semantic.xlsx')] + '.xlsx')
        relative = main.relative_to(data_root()).as_posix()
        info['review_main'] = None
        try:
            task = find_task(data_root(), file_path)
            if main.is_file() and (task is None or relative in task_files(data_root(), task)):
                info['review_main'] = relative
        except (OSError, ValueError, KeyError):
            pass  # Broken lineage must not silently select another collection.
    return info


@router.get("/files")
async def list_data_files(platform: Optional[str] = None, file_type: Optional[str] = None):
    """Get data file list"""
    root = data_root()
    if not root.exists():
        return {"files": []}

    files = []
    for file_path in collection_files(root):
        if platform and platform.lower() not in file_path.relative_to(root).as_posix().lower():
            continue
        if file_type and file_path.suffix[1:].lower() != file_type.lower():
            continue
        try:
            files.append(get_file_info(file_path))
        except OSError:
            continue

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x["modified_at"], reverse=True)

    return {"files": files}


@router.get("/files/{file_path:path}")
async def get_file_content(file_path: str, preview: bool = True, limit: int = 100):
    """Get file content or preview"""
    full_path = resolve_file(file_path)

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Security check: ensure within DATA_DIR
    try:
        full_path.resolve().relative_to(data_root())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if preview:
        # Return preview data
        try:
            if full_path.suffix == ".jsonl":
                from api.services.data_browser import read_rows
                rows = read_rows(full_path)
                return {"data": rows[:limit], "total": len(rows)}
            elif full_path.suffix == ".json":
                with open(full_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {"data": data[:limit], "total": len(data)}
                    return {"data": data, "total": 1}
            elif full_path.suffix == ".csv":
                import csv
                with open(full_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= limit:
                            break
                        rows.append(row)
                    # Re-read to get total count
                    f.seek(0)
                    total = sum(1 for _ in f) - 1
                    return {"data": rows, "total": total}
            elif full_path.suffix.lower() in (".xlsx", ".xls"):
                import pandas as pd
                # Read first limit rows
                df = pd.read_excel(full_path, nrows=limit)
                # Get total row count (only read first column to save memory)
                df_count = pd.read_excel(full_path, usecols=[0])
                total = len(df_count)
                # Convert to list of dictionaries, handle NaN values
                rows = df.where(pd.notnull(df), None).to_dict(orient='records')
                return {
                    "data": rows,
                    "total": total,
                    "columns": list(df.columns)
                }
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type for preview")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Return file download
        return FileResponse(
            path=full_path,
            filename=full_path.name,
            media_type="application/octet-stream"
        )


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download file"""
    full_path = resolve_file(file_path)

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Security check
    try:
        full_path.resolve().relative_to(data_root())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )


@router.get("/stats")
async def get_data_stats():
    """Get data statistics"""
    root = data_root()
    if not root.exists():
        return {"total_files": 0, "total_size": 0, "by_platform": {}, "by_type": {}}

    stats = {
        "total_files": 0,
        "total_size": 0,
        "by_platform": {},
        "by_type": {}
    }

    for file_path in collection_files(root):
        try:
            stat = file_path.stat()
            stats["total_files"] += 1
            stats["total_size"] += stat.st_size
            file_type = file_path.suffix[1:].lower()
            stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1
            rel_path = str(file_path.relative_to(root))
            for platform in ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]:
                if platform in rel_path.lower():
                    stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                    break
        except OSError:
            continue

    return stats
