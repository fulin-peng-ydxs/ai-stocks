"""应用服务层包：编排日常流程、回测任务、数据入库。"""

from backend.services.ingest import IngestionService

__all__ = ["IngestionService"]
