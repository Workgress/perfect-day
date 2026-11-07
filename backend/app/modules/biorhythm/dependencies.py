from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import Clock
from app.db.session import get_session
from app.modules.biorhythm.cache import BiorhythmCache
from app.modules.biorhythm.service import BiorhythmService
from app.modules.users.dependencies import get_clock


def get_biorhythm_cache(request: Request) -> BiorhythmCache:
    cache: BiorhythmCache = request.app.state.biorhythm_cache
    return cache


def get_biorhythm_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    cache: Annotated[BiorhythmCache, Depends(get_biorhythm_cache)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> BiorhythmService:
    return BiorhythmService(session, cache, clock)
