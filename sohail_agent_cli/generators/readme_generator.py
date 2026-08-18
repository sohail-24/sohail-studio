"""README and documentation generator."""

from __future__ import annotations

from pathlib import Path

from sohail_agent_cli.analyzers import RepoAnalysis, StackType


class ReadmeGenerator:
    """Generator for README and documentation files."""
    
    def generate(
        self,
        analysis: RepoAnalysis,
        include_deployment: bool = True,
    ) -> tuple[str, str | None]:
        """
        Generate README and optional DEPLOYMENT.md.
        
        Returns:
            Tuple of (readme, deployment or None)
        """
        readme = self._generate_readme(analysis)
        deployment = None
        
        if include_deployment and (analysis.has_docker or analysis.has_k8s):
            deployment = self._generate_deployment(analysis)
        
        return readme, deployment
    
    def _generate_readme(self, analysis: RepoAnalysis) -> str:
        """Generate README.md content."""
        name = analysis.name
        stack = analysis.stack.primary
        deps = analysis.dependencies[:10]
        entry_points = analysis.entry_points[:3]
        
        lines = [
            f"# {name}",
            "",
            f"A {stack.value} project.",
            "",
            "## Description",
            "",
            "Add a brief description of your project here.",
            "",
            "## Features",
            "",
            "- Feature 1",
            "- Feature 2",
            "- Feature 3",
            "",
            "## Tech Stack",
            "",
            f"- **Primary:** {stack.value}",
        ]
        
        if analysis.stack.secondary:
            lines.append(f"- **Secondary:** {', '.join(s.value for s in analysis.stack.secondary)}")
        
        lines.append("")
        
        # Prerequisites
        lines.extend([
            "## Prerequisites",
            "",
        ])
        
        prereqs = self._get_prerequisites(stack, analysis)
        for prereq in prereqs:
            lines.append(f"- {prereq}")
        
        lines.append("")
        
        # Installation
        lines.extend([
            "## Installation",
            "",
            "```bash",
            "# Clone the repository",
            f"git clone <repository-url>",
            f"cd {name}",
            "```",
            "",
        ])
        
        install_steps = self._get_install_steps(stack)
        if install_steps:
            lines.append("```bash")
            for step in install_steps:
                lines.append(step)
            lines.append("```")
            lines.append("")
        
        # Usage
        lines.extend([
            "## Usage",
            "",
        ])
        
        if entry_points:
            lines.append("### Running the application")
            lines.append("")
            lines.append("```bash")
            for ep in entry_points:
                run_cmd = self._get_run_command(stack, ep)
                lines.append(run_cmd)
            lines.append("```")
            lines.append("")
        
        # Docker
        if analysis.has_docker:
            lines.extend([
                "### Using Docker",
                "",
                "```bash",
                "# Build and run with Docker Compose",
                "docker-compose up --build",
                "",
                "# Or build and run manually",
                f"docker build -t {name} .",
                f"docker run -p 8000:8000 {name}",
                "```",
                "",
            ])
        
        # Testing
        if analysis.has_tests:
            lines.extend([
                "## Testing",
                "",
                "```bash",
            ])
            test_cmd = self._get_test_command(stack)
            lines.append(test_cmd)
            lines.append("```")
            lines.append("")
        
        # Key dependencies
        if deps:
            lines.extend([
                "## Key Dependencies",
                "",
            ])
            for dep in deps:
                lines.append(f"- {dep}")
            lines.append("")
        
        # Contributing
        lines.extend([
            "## Contributing",
            "",
            "1. Fork the repository",
            "2. Create a feature branch (`git checkout -b feature/amazing-feature`)",
            "3. Commit your changes (`git commit -m 'Add amazing feature'`)",
            "4. Push to the branch (`git push origin feature/amazing-feature`)",
            "5. Open a Pull Request",
            "",
        ])
        
        # License
        lines.extend([
            "## License",
            "",
            "This project is licensed under the MIT License - see the LICENSE file for details.",
            "",
        ])
        
        return "\n".join(lines)
    
    def _generate_deployment(self, analysis: RepoAnalysis) -> str:
        """Generate DEPLOYMENT.md content."""
        name = analysis.name
        stack = analysis.stack.primary
        
        lines = [
            f"# Deployment Guide: {name}",
            "",
            "This guide covers deployment options for this project.",
            "",
            "## Table of Contents",
            "",
        ]
        
        if analysis.has_docker:
            lines.append("- [Docker Deployment](#docker-deployment)")
        if analysis.has_k8s:
            lines.append("- [Kubernetes Deployment](#kubernetes-deployment)")
        lines.append("- [Environment Variables](#environment-variables)")
        lines.append("")
        
        # Docker section
        if analysis.has_docker:
            lines.extend([
                "## Docker Deployment",
                "",
                "### Local Development",
                "",
                "```bash",
                "# Build the image",
                f"docker build -t {name}:latest .",
                "",
                "# Run the container",
                f"docker run -p 8000:8000 {name}:latest",
                "```",
                "",
                "### Production",
                "",
                "```bash",
                "# Build with production settings",
                f"docker build -t {name}:production .",
                "",
                "# Run with environment variables",
                f"docker run -d \\",
                "  --name app \\",
                "  -p 8000:8000 \\",
                "  -e ENVIRONMENT=production \\",
                f"  {name}:production",
                "```",
                "",
            ])
        
        # K8s section
        if analysis.has_k8s:
            lines.extend([
                "## Kubernetes Deployment",
                "",
                "### Prerequisites",
                "",
                "- Kubernetes cluster (1.24+)",
                "- kubectl configured",
                "- Container registry access",
                "",
                "### Deploy",
                "",
                "```bash",
                "# Apply manifests",
                "kubectl apply -f k8s/",
                "",
                "# Or use kustomize",
                "kubectl apply -k k8s/",
                "",
                "# Check deployment status",
                f"kubectl get deployment {name}",
                "kubectl get pods",
                "kubectl get svc",
                "```",
                "",
                "### Scaling",
                "",
                "```bash",
                "# Scale to 3 replicas",
                f"kubectl scale deployment {name} --replicas=3",
                "```",
                "",
            ])
        
        # Environment variables
        lines.extend([
            "## Environment Variables",
            "",
            "| Variable | Description | Default |",
            "|----------|-------------|---------|",
            "| `PORT` | Server port | `8000` |",
            "| `ENVIRONMENT` | Environment name | `development` |",
            "| `LOG_LEVEL` | Logging level | `info` |",
            "",
            "## Health Checks",
            "",
            "The application exposes a health check endpoint:",
            "",
            "```",
            "GET /health",
            "```",
            "",
            "Expected response:",
            "",
            "```json",
            '{"status": "healthy"}',
            "```",
            "",
        ])
        
        return "\n".join(lines)
    
    def _get_prerequisites(self, stack: StackType, analysis: RepoAnalysis) -> list[str]:
        """Get prerequisites for a stack."""
        prereqs = []
        
        if stack in (StackType.PYTHON, StackType.DJANGO, StackType.FASTAPI, StackType.FLASK):
            prereqs.append("Python 3.11+")
            prereqs.append("pip or poetry")
        elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            prereqs.append("Node.js 18+")
            prereqs.append("npm or yarn")
        elif stack == StackType.GO:
            prereqs.append("Go 1.21+")
        elif stack == StackType.RUST:
            prereqs.append("Rust 1.75+")
        elif stack == StackType.JAVA:
            prereqs.append("Java 17+")
            prereqs.append("Maven or Gradle")
        elif stack in (StackType.RUBY, StackType.RAILS):
            prereqs.append("Ruby 3.0+")
            prereqs.append("Bundler")
        elif stack in (StackType.PHP, StackType.LARAVEL):
            prereqs.append("PHP 8.0+")
            prereqs.append("Composer")
        
        if analysis.has_docker:
            prereqs.append("Docker (optional)")
            prereqs.append("Docker Compose (optional)")
        
        return prereqs
    
    def _get_install_steps(self, stack: StackType) -> list[str]:
        """Get installation steps for a stack."""
        if stack in (StackType.PYTHON, StackType.DJANGO, StackType.FASTAPI, StackType.FLASK):
            return [
                "# Create virtual environment",
                "python -m venv venv",
                "source venv/bin/activate  # On Windows: venv\\Scripts\\activate",
                "",
                "# Install dependencies",
                "pip install -r requirements.txt",
                "# or: pip install -e .",
            ]
        elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            return [
                "# Install dependencies",
                "npm install",
                "# or: yarn install",
            ]
        elif stack == StackType.GO:
            return [
                "# Download dependencies",
                "go mod download",
            ]
        elif stack == StackType.RUST:
            return [
                "# Build the project",
                "cargo build --release",
            ]
        elif stack in (StackType.RUBY, StackType.RAILS):
            return [
                "# Install dependencies",
                "bundle install",
            ]
        elif stack in (StackType.PHP, StackType.LARAVEL):
            return [
                "# Install dependencies",
                "composer install",
            ]
        return []
    
    def _get_run_command(self, stack: StackType, entry_point: str) -> str:
        """Get run command for a stack."""
        if stack in (StackType.PYTHON, StackType.DJANGO, StackType.FASTAPI, StackType.FLASK):
            return f"python {entry_point}"
        elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            if entry_point.endswith(".js"):
                return f"node {entry_point}"
            return "npm start"
        elif stack == StackType.GO:
            return f"go run {entry_point}"
        elif stack == StackType.RUST:
            return "cargo run"
        elif stack in (StackType.RUBY, StackType.RAILS):
            if entry_point == "rails":
                return "rails server"
            return f"ruby {entry_point}"
        elif stack in (StackType.PHP, StackType.LARAVEL):
            if entry_point == "artisan":
                return "php artisan serve"
            return f"php {entry_point}"
        return f"./{entry_point}"
    
    def _get_test_command(self, stack: StackType) -> str:
        """Get test command for a stack."""
        if stack in (StackType.PYTHON, StackType.DJANGO, StackType.FASTAPI, StackType.FLASK):
            return "pytest"
        elif stack in (StackType.NODE, StackType.REACT, StackType.NEXTJS, StackType.VUE):
            return "npm test"
        elif stack == StackType.GO:
            return "go test ./..."
        elif stack == StackType.RUST:
            return "cargo test"
        elif stack in (StackType.RUBY, StackType.RAILS):
            return "bundle exec rspec"
        elif stack in (StackType.PHP, StackType.LARAVEL):
            return "php artisan test"
        return "echo 'Add test command'"
