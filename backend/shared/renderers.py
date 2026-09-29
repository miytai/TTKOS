"""Единый формат ответов API (TECHSPEC §11.1).

Все ответы имеют вид:

    {"data": ..., "meta": {...}, "errors": [...]}
"""

from rest_framework.renderers import JSONRenderer


class EnvelopeJSONRenderer(JSONRenderer):
    """Оборачивает любой ответ в конверт API.

    - ``{"results": [...], "next": ..., ...}``  → data=results, meta=остальное
    - ``{"data": ..., "meta": ...}``            → без изменений
    - списки и словари                            → оборачиваются в data
    - ``None``                                    → data=null, meta=null
    """

    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return super().render(self.wrap(data), accepted_media_type, renderer_context)

    @staticmethod
    def wrap(data):
        if data is None:
            return {"data": None, "meta": None, "errors": []}

        if isinstance(data, dict):
            if "data" in data and ("meta" in data or "errors" in data):
                data.setdefault("errors", [])
                return data
            if "results" in data:
                meta = {k: v for k, v in data.items() if k != "results"}
                meta.setdefault("page_size", len(data["results"]))
                return {"data": data["results"], "meta": meta, "errors": []}

        return {"data": data, "meta": {}, "errors": []}
