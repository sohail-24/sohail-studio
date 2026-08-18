"""Deployment readiness analyzer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .repo_analyzer import RepoAnalysis


@dataclass
class ReadinessReport:
    """Deployment readiness report."""
    score: int  # 0-100
    grade: str  # A, B, C, D, F
    gaps: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "score": self.score,
            "grade": self.grade,
            "gaps": self.gaps,
            "strengths": self.strengths,
            "recommendations": self.recommendations,
            "blockers": self.blockers,
        }


class DeploymentReadinessAnalyzer:
    """
    Analyzes deployment readiness of a project.
    
    Calculates a readiness score and identifies gaps
    that would prevent production deployment.
    """
    
    def analyze(self, repo_analysis: RepoAnalysis) -> ReadinessReport:
        """
        Analyze deployment readiness.
        
        Args:
            repo_analysis: The repository analysis
        
        Returns:
            ReadinessReport with score and recommendations
        """
        score = 0
        gaps: list[str] = []
        strengths: list[str] = []
        recommendations: list[str] = []
        blockers: list[str] = []
        
        # Stack detection confidence (up to 15 points)
        if repo_analysis.stack.confidence >= 0.8:
            score += 15
            strengths.append("Clear technology stack identification")
        elif repo_analysis.stack.confidence >= 0.5:
            score += 10
            gaps.append("Stack detection confidence could be improved")
        else:
            score += 5
            gaps.append("Technology stack unclear")
            recommendations.append("Add clear project markers (requirements.txt, package.json, etc.)")
        
        # Docker (20 points)
        if repo_analysis.has_docker:
            score += 20
            strengths.append("Dockerfile present")
        else:
            gaps.append("No Dockerfile")
            recommendations.append("Create Dockerfile for containerization")
            blockers.append("Dockerfile required for containerized deployment")
        
        # Docker Compose (5 points)
        if repo_analysis.has_docker_compose:
            score += 5
            strengths.append("Docker Compose configuration present")
        
        # Tests (15 points)
        if repo_analysis.has_tests:
            score += 15
            strengths.append("Test suite present")
        else:
            gaps.append("No test suite")
            recommendations.append("Add tests for critical functionality")
        
        # CI/CD (15 points)
        if repo_analysis.has_ci_cd:
            score += 15
            strengths.append("CI/CD pipeline configured")
        else:
            gaps.append("No CI/CD pipeline")
            recommendations.append("Set up GitHub Actions for automated testing")
        
        # README (10 points)
        if repo_analysis.has_readme:
            score += 10
            strengths.append("README documentation present")
        else:
            gaps.append("No README.md")
            recommendations.append("Create README with setup instructions")
        
        # Kubernetes (10 points - bonus)
        if repo_analysis.has_k8s:
            score += 10
            strengths.append("Kubernetes manifests present")
        
        # Helm (5 points - bonus)
        if repo_analysis.has_helm:
            score += 5
            strengths.append("Helm charts present")
        
        # Environment config (5 points)
        if repo_analysis.has_env_example:
            score += 5
            strengths.append("Environment configuration documented")
        else:
            gaps.append("No .env.example file")
            recommendations.append("Create .env.example with required environment variables")
        
        # Cap score at 100
        score = min(score, 100)
        
        # Determine grade
        grade = self._get_grade(score)
        
        return ReadinessReport(
            score=score,
            grade=grade,
            gaps=gaps,
            strengths=strengths,
            recommendations=recommendations,
            blockers=blockers,
        )
    
    def _get_grade(self, score: int) -> str:
        """Get letter grade from score."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
