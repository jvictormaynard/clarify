"""Present style selection separately from confirmed application in Qt."""

from shared.localization import translate


def style_caption(state):
    if state.kind != "dictation":
        return ""
    requested = state.writing_style_requested
    if requested is None:
        return translate("Estilo: Padrão")
    name = {
        "natural": "Natural",
        "informal": "Informal",
        "organized": "Organizado",
    }.get(requested)
    if name is None:
        return translate("Estilo não aplicado")
    if state.phase in {"recording", "processing"}:
        return translate("Selecionado: {style}", style=translate(name))
    if (
        state.writing_style_applied == requested
        and state.writing_style_status == "applied"
    ):
        return translate("Aplicado: {style}", style=translate(name))
    return translate("Estilo não aplicado")
