"""Analysis router — trigger analysis, get frequency/trend/cluster/twisted results."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.agents.pattern_analysis import PatternAnalysisAgent
from app.schemas.analysis import AnalysisResults

router = APIRouter()


@router.post("/run", response_model=AnalysisResults)
async def run_analysis(subject: str, db: AsyncSession = Depends(get_db)):
    """Trigger full pattern analysis computation for a subject and return results."""
    agent = PatternAnalysisAgent(db=db)
    res = await agent.run(subject=subject)
    return res["results"]


@router.get("/summary", response_model=AnalysisResults)
async def get_analysis_summary(subject: str, db: AsyncSession = Depends(get_db)):
    """Get full aggregated analysis results for a subject."""
    agent = PatternAnalysisAgent(db=db)
    res = await agent.run(subject=subject)
    return res["results"]


@router.get("/frequency")
async def get_frequency(subject: str, db: AsyncSession = Depends(get_db)):
    """Get topic frequency results."""
    agent = PatternAnalysisAgent(db=db)
    res = await agent.run(subject=subject)
    return {
        "subject": subject,
        "frequency": res["results"]["frequency"],
        "mark_weights": res["results"]["mark_weights"],
    }


@router.get("/trends")
async def get_trends(subject: str, db: AsyncSession = Depends(get_db)):
    """Get year-over-year trend data."""
    agent = PatternAnalysisAgent(db=db)
    res = await agent.run(subject=subject)
    return {"subject": subject, "trends": res["results"]["trends"]}


@router.get("/clusters")
async def get_clusters(subject: str, db: AsyncSession = Depends(get_db)):
    """Get question-type cluster results."""
    agent = PatternAnalysisAgent(db=db)
    res = await agent.run(subject=subject)
    return {"subject": subject, "clusters": res["results"]["clusters"]}


@router.get("/twisted-pairs")
async def get_twisted_pairs(subject: str, db: AsyncSession = Depends(get_db)):
    """Get detected duplicate/twisted question pairs."""
    agent = PatternAnalysisAgent(db=db)
    res = await agent.run(subject=subject)
    return {"subject": subject, "twisted_pairs": res["results"]["twisted_pairs"]}
