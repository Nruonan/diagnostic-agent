from app.schemas.diagnosis import DiagnosisState, DiagnosisStatus


class ReportGenerator:
    def to_markdown(self, state: DiagnosisState) -> str:
        root = state.root_cause
        if state.status not in {DiagnosisStatus.COMPLETED, DiagnosisStatus.NEED_USER_INPUT} or root is None:
            error_text = "\n".join(f"- {error.stage}: {error.message}" for error in state.errors) or "- none"
            return (
                f"# Diagnosis Report\n\n"
                f"- Diagnosis ID: `{state.diagnosis_id}`\n"
                f"- Status: `{state.status.value}`\n"
                f"- Trigger: `{state.trigger_source}`\n\n"
                f"## Errors\n\n{error_text}\n"
            )

        evidence = "\n".join(f"- {item}" for item in root.evidence)
        fixes = "\n".join(f"{index}. {item}" for index, item in enumerate(root.fix_steps, start=1))
        missing = "\n".join(f"- {item}" for item in root.missing_information) or "- none"
        source_errors = ""
        if state.collected_data and state.collected_data.source_errors:
            source_errors = "\n".join(
                f"- {error.source}: {error.message}" for error in state.collected_data.source_errors
            )
        else:
            source_errors = "- none"

        return (
            f"# Diagnosis Report\n\n"
            f"- Diagnosis ID: `{state.diagnosis_id}`\n"
            f"- Status: `{state.status.value}`\n"
            f"- Trigger: `{state.trigger_source}`\n"
            f"- Fault: {state.fault_description}\n"
            f"- Confidence: `{root.confidence:.2f}`\n\n"
            f"## Root Cause\n\n{root.root_cause}\n\n"
            f"## Evidence\n\n{evidence}\n\n"
            f"## Fix Steps\n\n{fixes}\n\n"
            f"## Missing Information\n\n{missing}\n\n"
            f"## Data Source Issues\n\n{source_errors}\n\n"
            f"## Mermaid\n\n```mermaid\n{root.mermaid}\n```\n"
        )
