from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import httpx

from .config import Settings


class ZimbraError(RuntimeError):
    """Raised when Zimbra rejects or cannot process a request."""


class ZimbraClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        settings.validate_primary()
        self._settings = settings
        self._http = http_client or httpx.AsyncClient(
            timeout=settings.request_timeout,
            verify=settings.verify_tls,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            http2=True,
        )
        self._owns_http = http_client is None
        self._auth_token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _authenticate(self) -> str:
        async with self._auth_lock:
            if self._auth_token:
                return self._auth_token
            body = {
                "Header": {"context": {"_jsns": "urn:zimbra"}},
                "Body": {
                    "AuthRequest": {
                        "_jsns": "urn:zimbraAccount",
                        "account": {"_content": self._settings.username},
                        "password": {"_content": self._settings.password},
                    }
                },
            }
            response = await self._http.post(f"{self._settings.zimbra_url}/service/soap", json=body)
            response.raise_for_status()
            token = _path(response.json(), "Body", "AuthResponse", "authToken", "_content")
            if not isinstance(token, str) or not token:
                raise ZimbraError("Zimbra authentication did not return an auth token")
            self._auth_token = token
            return token

    async def _request(
        self, operation: str, namespace: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        token = await self._authenticate()
        body = {
            "Header": {
                "context": {
                    "_jsns": "urn:zimbra",
                    "authToken": {"_content": token},
                }
            },
            "Body": {operation: {"_jsns": namespace, **payload}},
        }
        response = await self._http.post(f"{self._settings.zimbra_url}/service/soap", json=body)
        if response.status_code in {401, 403}:
            self._auth_token = None
            token = await self._authenticate()
            body["Header"]["context"]["authToken"] = {"_content": token}
            response = await self._http.post(f"{self._settings.zimbra_url}/service/soap", json=body)
        response.raise_for_status()
        data = response.json()
        fault = _path(data, "Body", "Fault")
        if fault:
            raise ZimbraError("Zimbra SOAP request failed")
        result = _path(data, "Body", operation.replace("Request", "Response"))
        if not isinstance(result, Mapping):
            raise ZimbraError("Zimbra returned an unexpected SOAP response")
        return result

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        result = await self._request(
            "SearchRequest",
            "urn:zimbraMail",
            {"query": query, "limit": limit, "types": "conversation"},
        )
        messages = result.get("c", [])
        if isinstance(messages, Mapping):
            messages = [messages]
        return [dict(item) for item in messages if isinstance(item, Mapping)]

    async def read(self, message_id: str) -> dict[str, Any]:
        result = await self._request(
            "GetMsgRequest",
            "urn:zimbraMail",
            {"m": {"id": message_id}},
        )
        message = result.get("m", result)
        return dict(message) if isinstance(message, Mapping) else {"message": message}

    async def send(self, to: list[str], subject: str, body: str, message_id: str) -> dict[str, Any]:
        result = await self._request(
            "SendMsgRequest",
            "urn:zimbraMail",
            {
                "m": {
                    "e": [{"t": "t", "a": address} for address in to],
                    "su": {"_content": subject},
                    "mp": [{"ct": "text/plain", "content": {"_content": body}}],
                    "id": message_id,
                }
            },
        )
        return dict(result)

    async def list_folders(self) -> list[dict[str, Any]]:
        result = await self._request("GetFolderRequest", "urn:zimbraMail", {})
        folders = result.get("folder", [])
        return _flatten_named_items(folders)

    async def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        folder: dict[str, Any] = {"name": name}
        if parent_id:
            folder["l"] = parent_id
        result = await self._request("CreateFolderRequest", "urn:zimbraMail", {"folder": folder})
        created = result.get("folder", result)
        return dict(created) if isinstance(created, Mapping) else {"folder": created}

    async def list_tags(self) -> list[dict[str, Any]]:
        result = await self._request("GetTagRequest", "urn:zimbraMail", {})
        tags = result.get("tag", [])
        return _flatten_named_items(tags)

    async def create_tag(self, name: str, color: int | None = None) -> dict[str, Any]:
        tag: dict[str, Any] = {"name": name}
        if color is not None:
            tag["color"] = color
        result = await self._request("CreateTagRequest", "urn:zimbraMail", {"tag": tag})
        created = result.get("tag", result)
        return dict(created) if isinstance(created, Mapping) else {"tag": created}

    async def save_draft(
        self,
        to: list[str],
        subject: str,
        body: str,
        draft_id: str | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "e": [{"t": "t", "a": address} for address in to],
            "su": {"_content": subject},
            "mp": [{"ct": "text/plain", "content": {"_content": body}}],
        }
        if draft_id:
            message["id"] = draft_id
        result = await self._request("SaveDraftRequest", "urn:zimbraMail", {"m": message})
        saved = result.get("m", result)
        return dict(saved) if isinstance(saved, Mapping) else {"message": saved}

    async def list_attachments(self, message_id: str) -> list[dict[str, Any]]:
        message = await self.read(message_id)
        attachments: list[dict[str, Any]] = []
        _collect_attachments(message, attachments)
        return attachments

    async def message_action(
        self,
        action: str,
        message_ids: list[str],
        folder_id: str | None = None,
        tag_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": action,
            "m": [{"id": message_id} for message_id in message_ids],
        }
        if folder_id:
            payload["l"] = folder_id
        if tag_name:
            payload["tagNames"] = tag_name
        result = await self._request("MsgActionRequest", "urn:zimbraMail", payload)
        return dict(result)

    async def list_calendar_events(
        self, start: datetime, end: datetime, limit: int
    ) -> list[dict[str, Any]]:
        result = await self._request(
            "GetApptSummariesRequest",
            "urn:zimbraMail",
            {"s": _epoch_ms(start), "e": _epoch_ms(end), "limit": limit},
        )
        appointments = result.get("appt", [])
        if isinstance(appointments, Mapping):
            appointments = [appointments]
        return [dict(item) for item in appointments if isinstance(item, Mapping)][:limit]

    async def read_calendar_event(self, event_id: str) -> dict[str, Any]:
        result = await self._request("GetAppointmentRequest", "urn:zimbraMail", {"id": event_id})
        appointment = result.get("appt", result)
        return (
            dict(appointment) if isinstance(appointment, Mapping) else {"appointment": appointment}
        )

    async def free_busy(
        self, start: datetime, end: datetime, emails: list[str]
    ) -> list[dict[str, Any]]:
        result = await self._request(
            "FreeBusyRequest",
            "urn:zimbraMail",
            {"s": _epoch_ms(start), "e": _epoch_ms(end), "uid": emails},
        )
        busy = result.get("usr", result.get("fb", []))
        if isinstance(busy, Mapping):
            busy = [busy]
        return [dict(item) for item in busy if isinstance(item, Mapping)]

    async def search_contacts(self, query: str, limit: int) -> list[dict[str, Any]]:
        result = await self._request(
            "SearchRequest",
            "urn:zimbraMail",
            {"query": query, "types": "contact", "limit": limit},
        )
        contacts = result.get("cn", [])
        if isinstance(contacts, Mapping):
            contacts = [contacts]
        return [dict(item) for item in contacts if isinstance(item, Mapping)][:limit]

    async def list_tasks(self, query: str, limit: int) -> list[dict[str, Any]]:
        result = await self._request(
            "SearchRequest",
            "urn:zimbraMail",
            {"query": query, "types": "task", "limit": limit},
        )
        tasks = result.get("task", [])
        if isinstance(tasks, Mapping):
            tasks = [tasks]
        return [dict(item) for item in tasks if isinstance(item, Mapping)][:limit]

    async def list_briefcase(self, limit: int) -> list[dict[str, Any]]:
        result = await self._request("GetFolderRequest", "urn:zimbraMail", {"view": "document"})
        documents = result.get("folder", [])
        return _flatten_named_items(documents)[:limit]

    async def get_preferences(self) -> dict[str, Any]:
        result = await self._request("GetPrefsRequest", "urn:zimbraAccount", {})
        return dict(result)

    async def get_quota(self) -> dict[str, Any]:
        result = await self._request("GetQuotaUsageRequest", "urn:zimbraMail", {})
        return dict(result)

    async def get_share_info(self) -> list[dict[str, Any]]:
        result = await self._request("GetShareInfoRequest", "urn:zimbraMail", {})
        shares = result.get("share", [])
        if isinstance(shares, Mapping):
            shares = [shares]
        return [dict(item) for item in shares if isinstance(item, Mapping)]

    async def modify_preferences(self, preferences: Mapping[str, str]) -> dict[str, Any]:
        result = await self._request(
            "ModifyPrefsRequest", "urn:zimbraAccount", {"pref": dict(preferences)}
        )
        return dict(result)

    async def modify_share(
        self, folder_id: str, grantee: str, rights: str, revoke: bool = False
    ) -> dict[str, Any]:
        grant = {"zimbraId": grantee, "grant": rights}
        payload: dict[str, Any] = {"folder": {"id": folder_id}}
        payload["revoke"] = grant if revoke else None
        payload["grant"] = None if revoke else grant
        result = await self._request("ModifyFolderRulesRequest", "urn:zimbraMail", payload)
        return dict(result)

    async def save_briefcase_document(
        self, name: str, content: str, folder_id: str = "16", document_id: str | None = None
    ) -> dict[str, Any]:
        document: dict[str, Any] = {
            "name": name,
            "l": folder_id,
            "content": {"_content": content},
        }
        operation = "CreateDocumentRequest"
        if document_id:
            document["id"] = document_id
            operation = "ModifyDocumentRequest"
        result = await self._request(operation, "urn:zimbraMail", {"doc": document})
        saved = result.get("doc", result)
        return dict(saved) if isinstance(saved, Mapping) else {"document": saved}

    async def delete_briefcase_document(self, document_id: str) -> dict[str, Any]:
        result = await self._request(
            "DocumentActionRequest",
            "urn:zimbraMail",
            {"action": "delete", "doc": [{"id": document_id}]},
        )
        return dict(result)

    async def save_contact(
        self, fields: Mapping[str, str], folder_id: str = "7", contact_id: str | None = None
    ) -> dict[str, Any]:
        attributes = [{"n": name, "_content": value} for name, value in fields.items()]
        contact: dict[str, Any] = {"l": folder_id, "a": attributes}
        if contact_id:
            contact["id"] = contact_id
            operation = "ModifyContactRequest"
        else:
            operation = "CreateContactRequest"
        result = await self._request(operation, "urn:zimbraMail", {"cn": contact})
        saved = result.get("cn", result)
        return dict(saved) if isinstance(saved, Mapping) else {"contact": saved}

    async def delete_contact(self, contact_id: str) -> dict[str, Any]:
        result = await self._request(
            "ContactActionRequest",
            "urn:zimbraMail",
            {"action": "delete", "cn": [{"id": contact_id}]},
        )
        return dict(result)

    async def save_task(
        self, fields: Mapping[str, str], folder_id: str = "15", task_id: str | None = None
    ) -> dict[str, Any]:
        task: dict[str, Any] = {"l": folder_id, "f": fields}
        if task_id:
            task["id"] = task_id
            operation = "ModifyTaskRequest"
        else:
            operation = "CreateTaskRequest"
        result = await self._request(operation, "urn:zimbraMail", {"m": task})
        saved = result.get("m", result)
        return dict(saved) if isinstance(saved, Mapping) else {"task": saved}

    async def delete_task(self, task_id: str) -> dict[str, Any]:
        result = await self._request(
            "TaskActionRequest", "urn:zimbraMail", {"action": "delete", "m": [{"id": task_id}]}
        )
        return dict(result)

    async def get_admin_status(self) -> dict[str, Any]:
        result = await self._request("GetServerStatsRequest", "urn:zimbraAdmin", {})
        return dict(result)


def _path(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _epoch_ms(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("calendar datetimes must include a timezone")
    return int(value.timestamp() * 1000)


def _flatten_named_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        items = [dict(value)]
    elif isinstance(value, list):
        items = [dict(item) for item in value if isinstance(item, Mapping)]
    else:
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        children = item.pop("folder", [])
        result.append(item)
        result.extend(_flatten_named_items(children))
    return result


def _collect_attachments(value: Any, result: list[dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        if "filename" in value or "aid" in value:
            result.append(
                {
                    key: value[key]
                    for key in ("filename", "aid", "part", "size", "ct")
                    if key in value
                }
            )
        for child in value.values():
            _collect_attachments(child, result)
    elif isinstance(value, list):
        for child in value:
            _collect_attachments(child, result)
