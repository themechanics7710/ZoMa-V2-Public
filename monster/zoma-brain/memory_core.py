"""
ZoMa Brain — FAISS-backed long-term memory
Property of TheMechanics. Contact: mamau.mechanics@gmail.com

One memory database per brain name: conversation turns, vision events,
and uploaded-document summaries, embedded and stored in a FAISS index
with a parallel JSON map of metadata.
"""

import os
import json
import time
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

import config

META_KEY = "__meta__"


class BrainMemory:
    def __init__(
        self,
        index_file: str = None,
        map_file: str = None,
        model_name: str = None,
        assistant_name: str = None,
    ):
        self.index_file = index_file or config.memory_paths("default")[0]
        self.map_file = map_file or config.memory_paths("default")[1]
        self.model_name = model_name or config.MEMORY_EMBED_MODEL
        self.assistant_name = assistant_name or config.ASSISTANT_NAME

        os.makedirs(os.path.dirname(self.index_file) or ".", exist_ok=True)

        print(f"[*] Initializing Memory Core for '{self.assistant_name}'...")
        print(f"    index: {self.index_file}")
        print(f"    map:   {self.map_file}")

        self.model = SentenceTransformer(self.model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()

        self._load(first_load=True)

    # --- load / integrity -----------------------------------------------------

    def _load(self, first_load: bool = False):
        if os.path.exists(self.index_file):
            self.index = faiss.read_index(self.index_file)
            print(f" [*] Loaded FAISS index with {self.index.ntotal} vectors.")
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            print(" [*] Created new empty FAISS index.")

        if os.path.exists(self.map_file):
            with open(self.map_file, "r", encoding="utf-8") as f:
                self.memory_map = json.load(f)
        else:
            self.memory_map = {}

        if first_load:
            self._check_embedding_model()
            self._check_integrity()

        self.memory_map.setdefault(
            META_KEY,
            {"type": META_KEY, "embed_model": self.model_name, "dimension": self.dimension},
        )

    def _entry_count(self) -> int:
        """Number of real records, excluding the meta record."""
        return len([k for k in self.memory_map if k != META_KEY])

    def _check_embedding_model(self):
        meta = self.memory_map.get(META_KEY)
        if not meta:
            return  # pre-stamp database, or a brand-new one -- nothing to compare
        stored = meta.get("embed_model")
        if stored and stored != self.model_name:
            raise RuntimeError(
                f"\n  Embedding model mismatch.\n"
                f"  This memory was built with '{stored}', but the server is "
                f"configured for '{self.model_name}'.\n"
                f"  The vectors are not comparable across models. Either set "
                f"MEMORY_EMBED_MODEL back to '{stored}', or delete both files "
                f"to start fresh:\n"
                f"    {self.index_file}\n"
                f"    {self.map_file}\n"
            )

    def _check_integrity(self):
        n_index = self.index.ntotal
        n_map = self._entry_count()
        if n_index == n_map:
            return

        message = (
            f"\n  Memory database is inconsistent.\n"
            f"  FAISS index holds {n_index} vectors, but the map holds "
            f"{n_map} records.\n"
            f"  These two files are one database and must be deleted or "
            f"restored together:\n"
            f"    {self.index_file}\n"
            f"    {self.map_file}\n"
        )

        if config.MEMORY_ON_MISMATCH == "reset":
            print(f"[!] {message}  MEMORY_ON_MISMATCH=reset -- wiping both and starting clean.")
            self.index = faiss.IndexFlatL2(self.dimension)
            self.memory_map = {}
            return

        raise RuntimeError(
            message + "  (Set MEMORY_ON_MISMATCH=reset to wipe automatically instead.)"
        )

    # --- persistence -----------------------------------------------------------

    def save_to_disk(self):
        faiss.write_index(self.index, self.index_file)
        with open(self.map_file, "w", encoding="utf-8") as f:
            json.dump(self.memory_map, f, indent=4, ensure_ascii=False)

    def reload(self):
        print(" [MEMORY] Hot-reloading database from disk...")
        self._load(first_load=False)
        print(f" [MEMORY] Reload complete. {self.index.ntotal} vectors currently in RAM.")

    # --- writes ------------------------------------------------------------------

    def _add(self, memory_string: str, entry: dict):
        vector = self.model.encode([memory_string]).astype(np.float32)
        faiss_id = self.index.ntotal
        self.index.add(vector)
        entry["full_text"] = memory_string
        self.memory_map[str(faiss_id)] = entry
        return faiss_id

    def add_memory(self, speaker: str, user_text: str, ai_response: str,
                   source: str = None, responder_name: str = None):
        """
        source is an optional audit tag (e.g. "claude" for an
        uplink-answered turn) -- an inert extra key to every existing
        reader, since search_memory() only ever surfaces "full_text".

        responder_name overrides who the memory TEXT ITSELF says replied
        (defaults to self.assistant_name). This matters because the
        stored full_text is fed back to a model verbatim on recall, and
        the local persona's name must not be misattributed to a
        different model's (e.g. Claude's) reply.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        responder = responder_name or self.assistant_name
        memory_string = (
            f"[{timestamp}] {speaker} asked: '{user_text}' | "
            f"{responder} replied: '{ai_response}'"
        )
        entry = {"type": "conversation", "speaker": speaker}
        if source:
            entry["source"] = source
        faiss_id = self._add(memory_string, entry)
        print(f" [MEMORY] Saved interaction #{faiss_id} for {speaker}.")

    def add_vision_event(self, description: str, trigger_reason: str = "unspecified", source: str = None):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        memory_string = f"[{timestamp}] [VISION EVENT: {trigger_reason}] {description}"
        entry = {"type": "vision_event", "trigger": trigger_reason}
        if source:
            entry["source"] = source
        faiss_id = self._add(memory_string, entry)
        print(f" [MEMORY] Saved vision event #{faiss_id} ({trigger_reason}).")

    def add_document_summary(self, uploader: str, filename: str, summary: str, upload_date: str):
        memory_string = (
            f"[UPLOADED ON: {upload_date}] {uploader} uploaded a document named "
            f"'{filename}'. Summary: {summary}"
        )
        self._add(memory_string, {"type": "doc_summary", "filename": filename})
        self.save_to_disk()
        print(f" [MEMORY] Saved Document Summary for {filename}.")

    def add_document_chunk(self, filename: str, chunk_text: str, upload_date: str):
        memory_string = f"[UPLOADED ON: {upload_date}] [DOCUMENT: {filename}] Extract: \"{chunk_text}\""
        self._add(memory_string, {"type": "doc_chunk", "filename": filename})
        # Not saved per-chunk; caller saves once at the end.

    # --- reads ---------------------------------------------------------------------

    def search_memory(self, query_text: str, top_k: int = None, distance_threshold: float = None):
        top_k = top_k or config.MEMORY_TOP_K
        distance_threshold = (
            distance_threshold if distance_threshold is not None
            else config.MEMORY_DISTANCE_THRESHOLD
        )

        if self.index.ntotal == 0:
            return []

        query_vector = self.model.encode([query_text]).astype(np.float32)
        distances, indices = self.index.search(query_vector, top_k)

        results = []
        for i, memory_id in enumerate(indices[0]):
            if memory_id == -1:
                continue
            distance_score = distances[0][i]
            if distance_score > distance_threshold:
                print(f" [MEMORY] Ignored irrelevant memory (Score: {distance_score:.2f})")
                continue

            entry = self.memory_map.get(str(memory_id))
            if entry is None:
                # Defensive: should be impossible after the load-time
                # integrity check, but a mid-session crash between
                # index.add() and the map write could still produce it.
                print(f" [MEMORY] WARNING: FAISS id {memory_id} has no map record -- skipping.")
                continue

            matched_text = entry["full_text"]

            # Vision events are short, sparse strings, so they sit at a
            # higher L2 distance than a full conversational turn even
            # when they're the most relevant thing in the index. Tag
            # them as confirmed system logs so the LLM treats them as
            # ground truth rather than discounting them for a weak
            # similarity score.
            if entry.get("type") == "vision_event":
                results.append(
                    f"(Relevance Score: {distance_score:.2f}) "
                    f"[CONFIRMED SYSTEM LOG - VISION EVENT] {matched_text}"
                )
            else:
                results.append(f"(Relevance Score: {distance_score:.2f}) {matched_text}")

        return results
