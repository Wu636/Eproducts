from __future__ import annotations

import json
import re
import ssl
import time
import uuid
from copy import deepcopy
from threading import Lock, Thread
from urllib import error, parse, request

from config import settings


class AnimateAnyoneError(RuntimeError):
    pass


_workflows = {}
_workflow_lock = Lock()


def is_configured():
    return bool(settings.video_api_base and settings.video_api_key and settings.video_model and settings.video_motion_model)


def _require_configured():
    if not is_configured():
        raise AnimateAnyoneError(
            "人物动作视频模型尚未配置：请在后端配置 XHS_VIDEO_API_KEY（或 DASHSCOPE_API_KEY）后重启服务"
        )


def _url(path):
    return settings.video_api_base.rstrip("/") + "/" + path.lstrip("/")


def _headers(*, asynchronous=False, oss_resource=False):
    headers = {
        "Authorization": f"Bearer {settings.video_api_key}",
        "Content-Type": "application/json",
    }
    if asynchronous:
        headers["X-DashScope-Async"] = "enable"
    if oss_resource:
        headers["X-DashScope-OssResourceResolve"] = "enable"
    return headers


def _ssl_context():
    return None if settings.video_ssl_verify else ssl._create_unverified_context()


def _request_json(method, url, payload=None, headers=None, timeout=300):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with request.urlopen(req, timeout=timeout, context=_ssl_context()) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
            message = detail.get("message") or detail.get("output", {}).get("message") or raw
            code = detail.get("code") or detail.get("output", {}).get("code")
            if code:
                message = f"{code}: {message}"
        except (json.JSONDecodeError, AttributeError):
            message = raw or str(exc)
        raise AnimateAnyoneError(f"阿里云百炼请求失败（HTTP {exc.code}）：{message}") from exc
    except error.URLError as exc:
        raise AnimateAnyoneError(f"无法连接阿里云百炼：{exc.reason}") from exc


def _encode_multipart(fields, file_field, filename, content_type, content):
    boundary = "----Eproducts" + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", filename or "upload.bin").strip("-") or "upload.bin"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"\r\n'.encode(),
            f"Content-Type: {content_type or 'application/octet-stream'}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return boundary, b"".join(chunks), safe_name


def upload_temporary_file(file_data, model):
    """Upload one browser-provided file to DashScope's model-bound 48h storage."""

    _require_configured()
    content = file_data.get("content") or b""
    filename = file_data.get("filename") or "upload.bin"
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in {"jpg", "jpeg", "png", "bmp", "webp"}:
        if len(content) >= 5 * 1024 * 1024:
            raise AnimateAnyoneError("人物图片必须小于 5MB")
    elif suffix in {"mp4", "avi", "mov"}:
        if len(content) > 200 * 1024 * 1024:
            raise AnimateAnyoneError("参考动作视频不能超过 200MB")
    else:
        raise AnimateAnyoneError("文件格式不受支持；图片请用 JPG/PNG/BMP/WEBP，视频请用 MP4/AVI/MOV")

    policy_url = _url("uploads") + "?" + parse.urlencode({"action": "getPolicy", "model": model})
    policy_response = _request_json("GET", policy_url, headers=_headers(), timeout=60)
    policy = policy_response.get("data") or {}
    required = {"upload_host", "upload_dir", "oss_access_key_id", "signature", "policy"}
    if not required.issubset(policy):
        raise AnimateAnyoneError("阿里云未返回完整的临时文件上传凭证")

    original_name = filename
    unique_name = f"{uuid.uuid4().hex[:10]}-{original_name}"
    key = f"{policy['upload_dir'].rstrip('/')}/{re.sub(r'[^A-Za-z0-9._-]+', '-', unique_name)}"
    fields = {
        "OSSAccessKeyId": policy["oss_access_key_id"],
        "Signature": policy["signature"],
        "policy": policy["policy"],
        "x-oss-object-acl": policy.get("x_oss_object_acl", "private"),
        "x-oss-forbid-overwrite": policy.get("x_oss_forbid_overwrite", "true"),
        "key": key,
        "success_action_status": "200",
    }
    boundary, body, _ = _encode_multipart(
        fields,
        "file",
        unique_name,
        file_data.get("content_type") or "application/octet-stream",
        content,
    )
    req = request.Request(
        policy["upload_host"],
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=300, context=_ssl_context()) as response:
            if response.status not in {200, 201, 204}:
                raise AnimateAnyoneError(f"临时文件上传失败（HTTP {response.status}）")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AnimateAnyoneError(f"临时文件上传失败（HTTP {exc.code}）：{detail[:500]}") from exc
    return f"oss://{key}"


def _resolve_input(file_data, url, model):
    if file_data and file_data.get("content"):
        return upload_temporary_file(file_data, model)
    if isinstance(url, str) and url.startswith(("http://", "https://", "oss://")):
        return url
    raise AnimateAnyoneError("请上传文件，或填写可公网访问的 HTTP/HTTPS URL")


def detect_person_image(*, image_file=None, image_url=""):
    source = _resolve_input(image_file, image_url, settings.video_detect_model)
    return _request_json(
        "POST",
        _url("services/aigc/image2video/aa-detect"),
        {"model": settings.video_detect_model, "input": {"image_url": source}},
        _headers(oss_resource=source.startswith("oss://")),
    )


def submit_action_template(*, video_file=None, video_url=""):
    source = _resolve_input(video_file, video_url, settings.video_template_model)
    return _request_json(
        "POST",
        _url("services/aigc/image2video/aa-template-generation/"),
        {"model": settings.video_template_model, "input": {"video_url": source}},
        _headers(asynchronous=True, oss_resource=source.startswith("oss://")),
    )


def submit_dance_video(*, template_id, image_file=None, image_url="", use_ref_img_bg=False, video_ratio="9:16"):
    if not template_id:
        raise AnimateAnyoneError("template_id 不能为空")
    if video_ratio not in {"9:16", "3:4"}:
        raise AnimateAnyoneError("video_ratio 只能为 9:16 或 3:4")
    source = _resolve_input(image_file, image_url, settings.video_model)
    return _request_json(
        "POST",
        _url("services/aigc/image2video/video-synthesis/"),
        {
            "model": settings.video_model,
            "input": {"image_url": source, "template_id": template_id},
            "parameters": {"use_ref_img_bg": bool(use_ref_img_bg), "video_ratio": video_ratio},
        },
        _headers(asynchronous=True, oss_resource=source.startswith("oss://")),
    )


def submit_wan_motion_video(
    *,
    image_file=None,
    video_file=None,
    image_url="",
    video_url="",
    mode="wan-std",
    watermark=False,
    check_image=True,
):
    if mode not in {"wan-std", "wan-pro"}:
        raise AnimateAnyoneError("mode 只能为 wan-std 或 wan-pro")
    image_source = _resolve_input(image_file, image_url, settings.video_motion_model)
    video_source = _resolve_input(video_file, video_url, settings.video_motion_model)
    uses_oss = image_source.startswith("oss://") or video_source.startswith("oss://")
    return _request_json(
        "POST",
        _url("services/aigc/image2video/video-synthesis"),
        {
            "model": settings.video_motion_model,
            "input": {
                "image_url": image_source,
                "video_url": video_source,
                "watermark": bool(watermark),
            },
            "parameters": {"mode": mode, "check_image": bool(check_image)},
        },
        _headers(asynchronous=True, oss_resource=uses_oss),
    )


def get_provider_task(task_id):
    if not task_id:
        raise AnimateAnyoneError("task_id 不能为空")
    return _request_json("GET", _url(f"tasks/{parse.quote(task_id)}"), headers=_headers(), timeout=60)


def _task_id(response):
    return (response.get("output") or {}).get("task_id") or ""


def _wait_for_task(task_id, workflow_id, stage, start_progress, end_progress):
    deadline = time.monotonic() + settings.video_max_wait
    while time.monotonic() < deadline:
        result = get_provider_task(task_id)
        output = result.get("output") or {}
        status = str(output.get("task_status") or "UNKNOWN").upper()
        _update_workflow(
            workflow_id,
            provider_status=status,
            progress=min(end_progress - 1, start_progress + 3),
            detail=f"{stage}：{status}",
        )
        if status == "SUCCEEDED":
            return result
        if status in {"FAILED", "UNKNOWN", "CANCELED", "CANCELLED"}:
            message = output.get("message") or "任务执行失败"
            code = output.get("code")
            raise AnimateAnyoneError(f"{stage}失败：{code + ': ' if code else ''}{message}")
        time.sleep(settings.video_poll_interval)
    raise AnimateAnyoneError(f"{stage}等待超时，请稍后通过任务 ID 查询")


def _public_workflow(item):
    return {key: deepcopy(value) for key, value in item.items() if not key.startswith("_")}


def _update_workflow(workflow_id, **changes):
    with _workflow_lock:
        item = _workflows.get(workflow_id)
        if not item:
            return
        item.update(changes)
        item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")


def create_workflow(
    *,
    image_file=None,
    video_file=None,
    image_url="",
    video_url="",
    engine="animate-anyone",
    use_ref_img_bg=False,
    video_ratio="9:16",
    mode="wan-std",
    watermark=False,
):
    _require_configured()
    if engine not in {"animate-anyone", "wan-move"}:
        raise AnimateAnyoneError("engine 只能为 animate-anyone 或 wan-move")
    if engine == "wan-move" and mode not in {"wan-std", "wan-pro"}:
        raise AnimateAnyoneError("mode 只能为 wan-std 或 wan-pro")
    if not image_file and not image_url:
        raise AnimateAnyoneError("请上传 AI 人物形象图片")
    if not video_file and not video_url:
        raise AnimateAnyoneError("请上传参考动作视频")
    workflow_id = "dance_" + uuid.uuid4().hex
    item = {
        "id": workflow_id,
        "status": "PENDING",
        "stage": "queued",
        "progress": 1,
        "detail": "任务已创建，等待处理",
        "engine": engine,
        "use_ref_img_bg": bool(use_ref_img_bg),
        "video_ratio": video_ratio,
        "mode": mode,
        "watermark": bool(watermark),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with _workflow_lock:
        _workflows[workflow_id] = item
    Thread(
        target=_run_workflow,
        kwargs={
            "workflow_id": workflow_id,
            "image_file": image_file,
            "video_file": video_file,
            "image_url": image_url,
            "video_url": video_url,
            "engine": engine,
            "use_ref_img_bg": use_ref_img_bg,
            "video_ratio": video_ratio,
            "mode": mode,
            "watermark": watermark,
        },
        daemon=True,
    ).start()
    return _public_workflow(item)


def _run_workflow(
    *, workflow_id, image_file, video_file, image_url, video_url,
    engine="animate-anyone", use_ref_img_bg=False, video_ratio="9:16", mode="wan-std", watermark=False,
):
    if engine == "wan-move":
        _run_wan_motion_workflow(
            workflow_id=workflow_id,
            image_file=image_file,
            video_file=video_file,
            image_url=image_url,
            video_url=video_url,
            mode=mode,
            watermark=watermark,
        )
        return
    try:
        _update_workflow(workflow_id, status="RUNNING", stage="image_check", progress=5, detail="正在上传并检测人物图片")
        image_check = detect_person_image(image_file=image_file, image_url=image_url)
        check_output = image_check.get("output") or {}
        _update_workflow(workflow_id, image_check=image_check, progress=18)
        if not check_output.get("check_pass"):
            reason = check_output.get("reason") or "人物图片不符合 AnimateAnyone 输入规范"
            raise AnimateAnyoneError(f"人物图片检测未通过：{reason}")

        _update_workflow(workflow_id, stage="template_upload", progress=22, detail="正在上传参考动作视频")
        template_submit = submit_action_template(video_file=video_file, video_url=video_url)
        video_file = None  # Release the potentially large browser upload after DashScope accepts it.
        template_task_id = _task_id(template_submit)
        if not template_task_id:
            raise AnimateAnyoneError("动作模板接口未返回 task_id")
        _update_workflow(
            workflow_id,
            stage="template_generation",
            progress=30,
            detail="正在提取动作并生成模板",
            template_task_id=template_task_id,
            template_submit=template_submit,
        )
        template_result = _wait_for_task(template_task_id, workflow_id, "动作模板生成", 30, 62)
        template_id = (template_result.get("output") or {}).get("template_id")
        if not template_id:
            raise AnimateAnyoneError("动作模板生成成功，但未返回 template_id")
        _update_workflow(workflow_id, template_id=template_id, template_result=template_result, progress=64)

        _update_workflow(workflow_id, stage="video_submit", progress=68, detail="正在提交 AI 舞蹈视频生成任务")
        video_submit = submit_dance_video(
            template_id=template_id,
            image_file=image_file,
            image_url=image_url,
            use_ref_img_bg=use_ref_img_bg,
            video_ratio=video_ratio,
        )
        video_task_id = _task_id(video_submit)
        if not video_task_id:
            raise AnimateAnyoneError("视频生成接口未返回 task_id")
        _update_workflow(
            workflow_id,
            stage="video_generation",
            progress=72,
            detail="AI 人物正在学习动作并生成视频",
            video_task_id=video_task_id,
            video_submit=video_submit,
        )
        video_result = _wait_for_task(video_task_id, workflow_id, "舞蹈视频生成", 72, 98)
        video_output = video_result.get("output") or {}
        video_result_url = video_output.get("video_url")
        if not video_result_url:
            raise AnimateAnyoneError("视频任务已完成，但未返回 video_url")
        _update_workflow(
            workflow_id,
            status="SUCCEEDED",
            stage="completed",
            progress=100,
            detail="AI 舞蹈视频生成完成",
            provider_status="SUCCEEDED",
            video_url=video_result_url,
            video_result=video_result,
        )
    except Exception as exc:
        _update_workflow(
            workflow_id,
            status="FAILED",
            stage="failed",
            detail="生成失败",
            error=str(exc),
        )


def _run_wan_motion_workflow(*, workflow_id, image_file, video_file, image_url, video_url, mode, watermark):
    try:
        _update_workflow(
            workflow_id,
            status="RUNNING",
            stage="wan_upload",
            progress=8,
            detail="正在上传人物图片与参考动作视频",
        )
        submit_result = submit_wan_motion_video(
            image_file=image_file,
            video_file=video_file,
            image_url=image_url,
            video_url=video_url,
            mode=mode,
            watermark=watermark,
            check_image=True,
        )
        task_id = _task_id(submit_result)
        if not task_id:
            raise AnimateAnyoneError("万相图生动作接口未返回 task_id")
        image_file = None
        video_file = None
        _update_workflow(
            workflow_id,
            stage="wan_generation",
            progress=28,
            detail="万相正在迁移动作与表情",
            video_task_id=task_id,
            video_submit=submit_result,
        )
        video_result = _wait_for_task(task_id, workflow_id, "万相动作模仿", 28, 98)
        output = video_result.get("output") or {}
        results = output.get("results") or {}
        video_result_url = results.get("video_url") if isinstance(results, dict) else ""
        video_result_url = video_result_url or output.get("video_url")
        if not video_result_url:
            raise AnimateAnyoneError("万相任务已完成，但未返回 video_url")
        _update_workflow(
            workflow_id,
            status="SUCCEEDED",
            stage="completed",
            progress=100,
            detail="万相动作模仿视频生成完成",
            provider_status="SUCCEEDED",
            video_url=video_result_url,
            video_result=video_result,
        )
    except Exception as exc:
        _update_workflow(
            workflow_id,
            status="FAILED",
            stage="failed",
            detail="生成失败",
            error=str(exc),
        )


def get_workflow(workflow_id):
    with _workflow_lock:
        item = _workflows.get(workflow_id)
        return _public_workflow(item) if item else None


def list_workflows():
    with _workflow_lock:
        return [_public_workflow(item) for item in reversed(list(_workflows.values()))]
