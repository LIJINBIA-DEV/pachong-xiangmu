# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/store/excel_store_base.py
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

# 声明:本代码仅供学习和研究目的使用。使用者应遵守以下原则:
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率,避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""
Excel Store Base Implementation
Provides Excel export functionality for crawled data with formatted sheets
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Any
from pathlib import Path

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

from base.base_crawler import AbstractStore
from tools import utils
from weibo_account_filter import account_record_reason
import config


class ExcelStoreBase(AbstractStore):
    """
    Base class for Excel storage implementation
    Provides formatted Excel export with multiple sheets for contents, comments, and creators
    Uses singleton pattern to maintain state across multiple store calls
    """

    # Class-level singleton management
    _instances: Dict[str, "ExcelStoreBase"] = {}
    _lock = threading.Lock()

    @classmethod
    async def finalize_semantic_note(
        cls, platform: str, note_id: str, comments_available: bool = True, *,
        comment_stop_reason: str | None = None,
    ) -> None:
        instance = cls._instances.get(f"{platform}_search")
        if instance and instance.semantic_stream:
            try:
                if comment_stop_reason is None:
                    await instance.semantic_stream.finalize_note(str(note_id), comments_available)
                else:
                    await instance.semantic_stream.finalize_note(
                        str(note_id), comments_available, comment_stop_reason=comment_stop_reason,
                    )
            finally:
                instance._write_retained_semantic_note(str(note_id))

    @classmethod
    async def review_semantic_note(cls, platform: str, note_id: str) -> str | None:
        """Review current evidence and stop collection only for a settled/pending post."""
        instance = cls._instances.get(f"{platform}_search")
        if not instance or not instance.semantic_stream:
            return None
        stream = instance.semantic_stream
        try:
            await stream.finalize_note(str(note_id), comments_available=False, interim=True)
        finally:
            instance._write_retained_semantic_note(str(note_id))
        active = [stream.states[key] for key in stream.note_keys.get(str(note_id), ()) if key in stream.active_keys]
        if not active or any(state.status is None for state in active):
            return None
        if any(state.status == "pending" for state in active):
            return "semantic_service_pending"
        return "evidence_found" if any(state.matched for state in active) else active[0].source

    @classmethod
    def semantic_note_retained(cls, platform: str, note_id: str, source_keyword: str | None = None) -> bool:
        instance = cls._instances.get(f"{platform}_search")
        if not instance or not instance.semantic_stream:
            return False
        stream = instance.semantic_stream
        if source_keyword is not None:
            state = stream.states.get((str(note_id), source_keyword))
            return bool(state and state.status == "matched")
        return any(
            stream.states[key].status == "matched"
            for key in stream.note_keys.get(str(note_id), ())
        )

    @classmethod
    def semantic_comments_collected(cls, platform: str, note_id: str, source_keyword: str, budget: int) -> bool:
        instance = cls._instances.get(f"{platform}_search")
        state = instance.semantic_stream.states.get((str(note_id), source_keyword)) if instance and instance.semantic_stream else None
        return bool(state and (state.note.get('comments_collection_complete') or
                    int(state.note.get('comments_collected_count') or 0) >= budget))

    @classmethod
    def semantic_note_media_needed(cls, platform: str, note_id: str, source_keyword: str) -> bool:
        """Review rows need images too; this does not promote them into the pass quota."""
        instance = cls._instances.get(f'{platform}_search')
        state = instance.semantic_stream.states.get((str(note_id), source_keyword)) if instance and instance.semantic_stream else None
        return bool(state and state.status in {'matched', 'review'})

    @classmethod
    def semantic_note_completed(cls, platform: str, note_id: str, source_keyword: str) -> bool:
        """Whether saved evidence can be finalized without fetching comments again."""
        instance = cls._instances.get(f"{platform}_search")
        if not instance or not instance.semantic_stream:
            return False
        state = instance.semantic_stream.states.get((str(note_id), source_keyword))
        return bool(state and (
            state.status in ("matched", "review", "excluded", "duplicate")
            or (state.status == "pending" and state.comments_available)
        ))

    @classmethod
    def semantic_progress(cls, platform: str, source_keyword: str) -> Dict[str, int]:
        instance = cls._instances.get(f"{platform}_search")
        counts = {"matched": 0, "review": 0, "excluded": 0, "pending": 0, "duplicate": 0}
        if instance and instance.semantic_stream:
            stream = instance.semantic_stream
            for key, state in stream.states.items():
                if key in stream.active_keys and key[1] == source_keyword:
                    counts[state.status or "pending"] += 1
        return counts

    @classmethod
    async def finalize_semantics_all(cls) -> None:
        for instance in list(cls._instances.values()):
            if instance.semantic_stream:
                try:
                    await instance.semantic_stream.close()
                finally:
                    for note_id in instance.semantic_stream.note_keys:
                        instance._write_retained_semantic_note(note_id)
                instance.semantic_stream = None

    @classmethod
    def get_instance(cls, platform: str, crawler_type: str) -> "ExcelStoreBase":
        """
        Get or create a singleton instance for the given platform and crawler type

        Args:
            platform: Platform name (xhs, dy, ks, etc.)
            crawler_type: Type of crawler (search, detail, creator)

        Returns:
            ExcelStoreBase instance
        """
        key = f"{platform}_{crawler_type}"
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = cls(platform, crawler_type)
            return cls._instances[key]

    @classmethod
    def flush_all(cls):
        """
        Flush all Excel store instances and save to files
        Should be called at the end of crawler execution
        """
        with cls._lock:
            for key, instance in cls._instances.items():
                try:
                    instance.flush()
                    utils.logger.info(f"[ExcelStoreBase] Flushed instance: {key}")
                except Exception as e:
                    utils.logger.error(f"[ExcelStoreBase] Error flushing {key}: {e}")
            cls._instances.clear()

    def __init__(self, platform: str, crawler_type: str = "search"):
        """
        Initialize Excel store

        Args:
            platform: Platform name (xhs, dy, ks, etc.)
            crawler_type: Type of crawler (search, detail, creator)
        """
        if not EXCEL_AVAILABLE:
            raise ImportError(
                "openpyxl is required for Excel export. "
                "Install it with: pip install openpyxl"
            )

        super().__init__()
        self.platform = platform
        self.crawler_type = crawler_type

        # Create data directory
        if config.SAVE_DATA_PATH:
            self.data_dir = Path(config.SAVE_DATA_PATH) / platform
        else:
            self.data_dir = Path("data") / platform
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize workbook
        self.workbook = openpyxl.Workbook()
        self.workbook.remove(self.workbook.active)  # Remove default sheet

        # Create sheets
        self.contents_sheet = self.workbook.create_sheet("Contents")
        self.comments_sheet = self.workbook.create_sheet("Comments")
        self.creators_sheet = self.workbook.create_sheet("Creators")

        # Track if headers are written
        self.contents_headers_written = False
        self.comments_headers_written = False
        self.creators_headers_written = False
        self.contacts_headers_written = False
        self.dynamics_headers_written = False

        # Optional sheets for platforms that need them (e.g., Bilibili)
        self.contacts_sheet = None
        self.dynamics_sheet = None

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = self.data_dir / f"{platform}_{crawler_type}_{timestamp}.xlsx"
        if os.environ.get('MEDIACRAWLER_COLLECTION_RUN'):
            run_id = Path(os.environ['MEDIACRAWLER_COLLECTION_RUN']).stem
            self.filename = self.filename.with_name(f'{self.filename.stem}_{run_id[:8]}.xlsx')

        self.semantic_stream = None
        self._semantic_pending_notes: Dict[tuple[str, str], Dict] = {}
        self._semantic_pending_comments: Dict[str, List[Dict]] = {}
        self._semantic_written_notes: set[tuple[str, str]] = set()
        self._semantic_written_rows: dict[tuple[str, str], tuple[str, int]] = {}
        self._semantic_written_comments: set[tuple[str, str]] = set()
        self._semantic_review_comments: set[tuple[str, str]] = set()
        if (
            os.environ.get("MEDIACRAWLER_SEMANTIC_FILTER") == "1"
            and platform in ("weibo", "xhs") and crawler_type == "search"
        ):
            from semantic_filter import MODEL, StreamingSemanticFilter, COMMENT_SAMPLE_LIMIT

            pairs = [tuple(pair) for pair in json.loads(os.environ.get("MEDIACRAWLER_KEYWORD_PAIRS", "[]"))]
            api_key = os.environ.get("TYPESAFE_API_KEY", "")
            model = os.environ.get("MEDIACRAWLER_SEMANTIC_MODEL", MODEL)
            if not pairs or (model == MODEL and not api_key):
                raise ValueError("Semantic filtering requires keyword pairs; Jev also requires a TypeSafe API Key")
            self.semantic_stream = StreamingSemanticFilter(
                self.filename, pairs, api_key,
                model=model,
                comment_budget=min(COMMENT_SAMPLE_LIMIT, max(0, config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES)),
            )

        utils.logger.info(f"[ExcelStoreBase] Initialized Excel export to: {self.filename}")

    def _apply_header_style(self, sheet, row_num: int = 1):
        """
        Apply formatting to header row

        Args:
            sheet: Worksheet object
            row_num: Row number for headers (default: 1)
        """
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )

        for cell in sheet[row_num]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = header_alignment
            cell.border = border

    def _auto_adjust_column_width(self, sheet):
        """
        Auto-adjust column widths based on content

        Args:
            sheet: Worksheet object
        """
        for column in sheet.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)

            for cell in column:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except (TypeError, AttributeError):
                    pass

            # Set width with min/max constraints
            adjusted_width = min(max(max_length + 2, 10), 50)
            sheet.column_dimensions[column_letter].width = adjusted_width

    def _write_headers(self, sheet, headers: List[str]):
        """
        Write headers to sheet

        Args:
            sheet: Worksheet object
            headers: List of header names
        """
        for col_num, header in enumerate(headers, 1):
            sheet.cell(row=1, column=col_num, value=header)

        self._apply_header_style(sheet)

    def _write_row(self, sheet, data: Dict[str, Any], headers: List[str]):
        """
        Write data row to sheet

        Args:
            sheet: Worksheet object
            data: Data dictionary
            headers: List of header names (defines column order)
        """
        # A later post can carry additional metadata. Keep existing columns in
        # place and append new ones, rather than writing by each row's key order.
        existing = [cell.value for cell in sheet[1] if cell.value is not None]
        headers = list(dict.fromkeys([*existing, *headers]))
        if headers != existing:
            self._write_headers(sheet, headers)
        if sheet is self.contents_sheet and data.get('metadata_version') and 'note_id' in headers:
            from weibo_metadata import reconcile_metadata
            id_column = headers.index('note_id')
            prior = [(row, dict(zip(headers, (cell.value for cell in row))))
                     for row in sheet.iter_rows(min_row=2)
                     if str(row[id_column].value) == str(data.get('note_id'))]
            changed = {id(record) for record in reconcile_metadata(data, [record for _, record in prior])}
            for row, record in prior:
                if id(record) not in changed:
                    continue
                for cell, header in zip(row, headers):
                    if cell.value != record.get(header):
                        cell.value = record.get(header)
                        if isinstance(cell.value, str):
                            cell.data_type = 's'
        row_num = sheet.max_row + 1

        for col_num, header in enumerate(headers, 1):
            value = data.get(header, "")

            # Handle different data types
            if isinstance(value, (list, dict)):
                value = str(value)
            elif value is None:
                value = ""

            cell = sheet.cell(row=row_num, column=col_num, value=value)
            if isinstance(value, str):
                cell.data_type = 's'

            # Apply basic formatting
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )

    async def store_content(self, content_item: Dict):
        """
        Store content data to Excel

        Args:
            content_item: Content data dictionary
        """
        if self.semantic_stream:
            await self.semantic_stream.add_note(content_item)
            key = (str(content_item.get("note_id") or ""), str(content_item.get("source_keyword") or ""))
            restored = self.semantic_stream.states.get(key)
            self._semantic_pending_notes[key] = dict(restored.note if restored else content_item)
            if restored and getattr(restored, "comments", None):
                self._semantic_pending_comments.setdefault(key[0], []).extend(restored.comments)
            return

        # Define headers (customize based on platform)
        headers = list(content_item.keys())

        # Write headers if first time
        if not self.contents_headers_written:
            self._write_headers(self.contents_sheet, headers)
            self.contents_headers_written = True

        # Write data row
        self._write_row(self.contents_sheet, content_item, headers)

        # Get ID from various possible field names
        content_id = content_item.get('note_id') or content_item.get('aweme_id') or content_item.get('video_id') or content_item.get('content_id') or 'N/A'
        from collection_tasks import review_progress
        review_progress("CRAWLING", content_id)
        utils.logger.info(f"[ExcelStoreBase] Stored content to Excel: {content_id}")

    async def store_comment(self, comment_item: Dict):
        """
        Store comment data to Excel

        Args:
            comment_item: Comment data dictionary
        """
        if self.platform == "weibo" and account_record_reason(comment_item):
            return
        if self.semantic_stream:
            await self.semantic_stream.add_comment(comment_item)
            note_id = str(comment_item.get("note_id") or "")
            self._semantic_pending_comments.setdefault(note_id, []).append(dict(comment_item))
            return

        # Define headers
        headers = list(comment_item.keys())

        # Write headers if first time
        if not self.comments_headers_written:
            self._write_headers(self.comments_sheet, headers)
            self.comments_headers_written = True

        # Write data row
        self._write_row(self.comments_sheet, comment_item, headers)

        utils.logger.info(f"[ExcelStoreBase] Stored comment to Excel: {comment_item.get('comment_id', 'N/A')}")

    def _write_retained_semantic_note(self, note_id: str) -> None:
        """Only materialize completed matched/review notes and their comments."""
        stream = self.semantic_stream
        if not stream:
            return
        destinations = set()
        for key in stream.note_keys.get(note_id, ()):
            state = stream.states[key]
            if state.status not in ("matched", "review"):
                if state.status == 'excluded' and key in self._semantic_written_rows:
                    sheet_name, row_number = self._semantic_written_rows.pop(key)
                    self.workbook[sheet_name].delete_rows(row_number)
                    self._semantic_written_notes.discard(key)
                    for other, (sheet, row) in list(self._semantic_written_rows.items()):
                        if sheet == sheet_name and row > row_number:
                            self._semantic_written_rows[other] = (sheet, row - 1)
                    if not any(stream.states[k].status in {'matched', 'review'} for k in stream.note_keys.get(note_id, ())):
                        for sheet in (self.comments_sheet, self.workbook['ReviewComments'] if 'ReviewComments' in self.workbook.sheetnames else None):
                            if sheet is None:
                                continue
                            headers = {cell.value: cell.column for cell in sheet[1]}
                            if 'note_id' in headers:
                                for row in range(sheet.max_row, 1, -1):
                                    if str(sheet.cell(row, headers['note_id']).value) == str(note_id):
                                        sheet.delete_rows(row)
                        self._semantic_written_comments = {item for item in self._semantic_written_comments if item[0] != str(note_id)}
                        self._semantic_review_comments = {item for item in self._semantic_review_comments if item[0] != str(note_id)}
                continue
            if key in self._semantic_pending_notes or key in self._semantic_written_notes:
                destinations.add(state.status)
            if key in self._semantic_written_notes:
                location = self._semantic_written_rows.get(key)
                if location:
                    saved_sheet, saved_row = location
                    sheet = self.workbook[saved_sheet]
                    headers = {cell.value: cell.column for cell in sheet[1]}
                    from weibo_metadata import refresh_metadata
                    saved = {name: sheet.cell(saved_row, column).value for name, column in headers.items()}
                    if refresh_metadata(saved, state.note):
                        for name, value in saved.items():
                            if name not in headers:
                                headers[name] = len(headers) + 1
                                sheet.cell(1, headers[name], name)
                            cell = sheet.cell(saved_row, headers[name])
                            cell.value = value
                            if isinstance(value, str):
                                cell.data_type = 's'
                    for name in ('comments_collected_count', 'comments_collection_complete', 'comments_collection_stop_reason'):
                        if name in headers:
                            sheet.cell(saved_row, headers[name], state.note.get(name))
                continue
            note = self._semantic_pending_notes.get(key)
            if note is None:
                continue
            from weibo_metadata import refresh_metadata
            refresh_metadata(note, state.note)
            # Keep the decision beside the note ID in the primary workbook so
            # a retained "review" row cannot be mistaken for a Jev "keep".
            annotated_note = {
                "note_id": note.get("note_id"),
                "semantic_result": state.status,
                "semantic_source": getattr(state, "source", None),
                "semantic_confidence": getattr(state, "confidence", None),
                "semantic_evidence": getattr(state, "evidence_text", None),
                "semantic_object_type": getattr(state, "object_type", None),
                "semantic_target_relation": getattr(state, "target_relation", None),
                "semantic_comments_available": getattr(state, "comments_available", False),
                "semantic_comments_checked": state.note.get("semantic_comments_checked"),
                "semantic_comment_budget": state.note.get("semantic_comment_budget"),
                "semantic_comment_stop_reason": state.note.get("semantic_comment_stop_reason"),
                "comments_collected_count": state.note.get('comments_collected_count'),
                "comments_collection_complete": state.note.get('comments_collection_complete'),
                "comments_collection_stop_reason": state.note.get('comments_collection_stop_reason'),
                "evidence_source": getattr(state, "evidence_source", None),
                "target_evidence": getattr(state, "target_evidence_text", None),
                "target_evidence_source": getattr(state, "target_evidence_source", None),
                "quality_reason": getattr(state, "quality_reason", None),
                "verification_confidence": getattr(state, "verification_confidence", None),
                "duplicate_of": getattr(state, "duplicate_of", None),
                "duplicate_kind": getattr(state, "duplicate_kind", None),
                "selection_origin": state.note.get("selection_origin"),
                "manual_review_required": state.note.get("manual_review_required"),
                "model_original_choice": state.note.get("model_original_choice") or state.note.get("jev_original_choice"),
                "model_original_object_type": state.note.get("model_original_object_type") or state.note.get("jev_original_object_type"),
                "jev_original_choice": state.note.get("model_original_choice") or state.note.get("jev_original_choice"),
                "jev_original_object_type": state.note.get("model_original_object_type") or state.note.get("jev_original_object_type"),
                "original_semantic_source": state.note.get("original_semantic_source"),
            }
            if state.note.get('semantic_rule') == 'topic':
                annotated_note.update(semantic_rule='topic', topic_evidence=state.note.get('topic_evidence'))
            if state.note.get('semantic_rule') == 'evaluation':
                annotated_note.update(semantic_rule='evaluation', evaluation_evidence=state.note.get('evaluation_evidence'),
                                      evaluation_target_evidence=state.note.get('evaluation_target_evidence'))
            annotated_note["semantic_rule_version"] = self.semantic_stream.rule_version
            annotated_note.update({name: value for name, value in note.items() if name not in annotated_note})
            headers = list(annotated_note)
            if state.status == "matched":
                sheet = self.contents_sheet
                if not self.contents_headers_written:
                    self._write_headers(sheet, headers)
                    self.contents_headers_written = True
            else:
                if "Review" not in self.workbook.sheetnames:
                    self._write_headers(self.workbook.create_sheet("Review"), headers)
                sheet = self.workbook["Review"]
            self._write_row(sheet, annotated_note, headers)
            self._semantic_written_notes.add(key)
            self._semantic_written_rows[key] = (sheet.title, sheet.max_row)
            self._semantic_pending_notes.pop(key, None)

        for destination in destinations:
            written = self._semantic_written_comments if destination == "matched" else self._semantic_review_comments
            for comment in self._semantic_pending_comments.get(note_id, []):
                key = (note_id, str(comment.get("comment_id") or id(comment)))
                if key in written:
                    continue
                headers = list(comment)
                if destination == "matched":
                    sheet = self.comments_sheet
                    if not self.comments_headers_written:
                        self._write_headers(sheet, headers)
                        self.comments_headers_written = True
                else:
                    if "ReviewComments" not in self.workbook.sheetnames:
                        self._write_headers(self.workbook.create_sheet("ReviewComments"), headers)
                    sheet = self.workbook["ReviewComments"]
                self._write_row(sheet, comment, headers)
                written.add(key)
        if all(stream.states[key].status in ("matched", "review", "excluded", "duplicate") for key in stream.note_keys.get(note_id, ())):
            self._semantic_pending_comments.pop(note_id, None)
        for key in stream.note_keys.get(note_id, ()):
            if stream.states[key].status in ("matched", "review", "excluded", "duplicate"):
                self._semantic_pending_notes.pop(key, None)

    async def store_creator(self, creator: Dict):
        """
        Store creator data to Excel

        Args:
            creator: Creator data dictionary
        """
        # Define headers
        headers = list(creator.keys())

        # Write headers if first time
        if not self.creators_headers_written:
            self._write_headers(self.creators_sheet, headers)
            self.creators_headers_written = True

        # Write data row
        self._write_row(self.creators_sheet, creator, headers)

        utils.logger.info(f"[ExcelStoreBase] Stored creator to Excel: {creator.get('user_id', 'N/A')}")

    async def store_contact(self, contact_item: Dict):
        """
        Store contact data to Excel (for platforms like Bilibili)

        Args:
            contact_item: Contact data dictionary
        """
        # Create contacts sheet if not exists
        if self.contacts_sheet is None:
            self.contacts_sheet = self.workbook.create_sheet("Contacts")

        # Define headers
        headers = list(contact_item.keys())

        # Write headers if first time
        if not self.contacts_headers_written:
            self._write_headers(self.contacts_sheet, headers)
            self.contacts_headers_written = True

        # Write data row
        self._write_row(self.contacts_sheet, contact_item, headers)

        utils.logger.info(f"[ExcelStoreBase] Stored contact to Excel: up_id={contact_item.get('up_id', 'N/A')}, fan_id={contact_item.get('fan_id', 'N/A')}")

    async def store_dynamic(self, dynamic_item: Dict):
        """
        Store dynamic data to Excel (for platforms like Bilibili)

        Args:
            dynamic_item: Dynamic data dictionary
        """
        # Create dynamics sheet if not exists
        if self.dynamics_sheet is None:
            self.dynamics_sheet = self.workbook.create_sheet("Dynamics")

        # Define headers
        headers = list(dynamic_item.keys())

        # Write headers if first time
        if not self.dynamics_headers_written:
            self._write_headers(self.dynamics_sheet, headers)
            self.dynamics_headers_written = True

        # Write data row
        self._write_row(self.dynamics_sheet, dynamic_item, headers)

        utils.logger.info(f"[ExcelStoreBase] Stored dynamic to Excel: {dynamic_item.get('dynamic_id', 'N/A')}")

    def flush(self):
        """
        Save workbook to file
        """
        try:
            # Auto-adjust column widths for all sheets
            self._auto_adjust_column_width(self.contents_sheet)
            self._auto_adjust_column_width(self.comments_sheet)
            self._auto_adjust_column_width(self.creators_sheet)
            for name in ("Review", "ReviewComments"):
                if name in self.workbook.sheetnames:
                    self._auto_adjust_column_width(self.workbook[name])
            if self.contacts_sheet is not None:
                self._auto_adjust_column_width(self.contacts_sheet)
            if self.dynamics_sheet is not None:
                self._auto_adjust_column_width(self.dynamics_sheet)

            # Remove empty sheets (only header row)
            if not self.contents_headers_written and "Review" in self.workbook.sheetnames:
                self._write_headers(self.contents_sheet, ["note_id", "semantic_result", "content", "source_keyword"])
                self.contents_headers_written = True
            if self.contents_sheet.max_row == 1 and "Review" not in self.workbook.sheetnames:
                self.workbook.remove(self.contents_sheet)
            if self.comments_sheet.max_row == 1:
                self.workbook.remove(self.comments_sheet)
            if self.creators_sheet.max_row == 1:
                self.workbook.remove(self.creators_sheet)
            if self.contacts_sheet is not None and self.contacts_sheet.max_row == 1:
                self.workbook.remove(self.contacts_sheet)
            if self.dynamics_sheet is not None and self.dynamics_sheet.max_row == 1:
                self.workbook.remove(self.dynamics_sheet)

            # Check if there are any sheets left
            if len(self.workbook.sheetnames) == 0:
                utils.logger.info(f"[ExcelStoreBase] No data to save, skipping file creation: {self.filename}")
                return

            # Save workbook
            self.workbook.save(self.filename)
            from collection_tasks import register_output
            register_output(self.filename)
            utils.logger.info(f"[ExcelStoreBase] Excel file saved successfully: {self.filename}")

        except Exception as e:
            utils.logger.error(f"[ExcelStoreBase] Error saving Excel file: {e}")
            raise
