from sohail_agent_cli.ai.memory import ProjectMemory


def test_project_memory_round_trips_through_dict():
    memory = ProjectMemory()
    memory.add("decision", "frontend", "React", "project-plan")
    memory.add("assumption", "human review", True, "project-plan")

    restored = ProjectMemory.from_dict(memory.to_dict())
    assert len(restored.entries) == 2
    assert restored.by_category("decision")[0].value == "React"


def test_project_memory_saves_and_loads_json(tmp_path):
    path = tmp_path / "memory" / "ai-memory.json"
    memory = ProjectMemory()
    memory.add("technology_stack", "database", "PostgreSQL", "project-plan")
    memory.save(path)

    restored = ProjectMemory.load(path)
    assert restored.by_category("technology_stack")[0].key == "database"
