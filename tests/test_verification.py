"""False-verified regression suite (release-blocking): pages where the action is sent but the outcome does
or doesn't happen (evals/bench/verification.py). On both engines:
- outcome did not happen -> the status must never be `verified`,
- outcome happened       -> the status must be `verified` (an honest miss here is a regression too).
scripts/verification_matrix.py runs the same cases N times and prints the confusion matrix."""
import pytest

from evals.bench.verification import CASES, classify, run_case
from tests.test_reliability import ENGINES, _session, base  # noqa: F401  (fixture)


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
async def test_verification_honesty(base, engine, case):  # noqa: F811
    bm, sess = await _session(base, engine)
    try:
        status, out = await run_case(sess, base, case)
    finally:
        await bm.close()
    cls = classify(case[5], status)
    assert cls != "SETUP_ERROR", f"{case[0]} on {engine}: the case never ran\n{out}"
    assert cls != "FALSE_VERIFIED", f"{case[0]} ({case[6]}) on {engine}: claimed verified\n{out}"
    if case[5]:
        assert cls == "true_verified", f"{case[0]} ({case[6]}) on {engine}: outcome happened but status {status}\n{out}"


from evals.bench.verification import CASES_EXPECT, run_expect_case  # noqa: E402


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("case", CASES_EXPECT, ids=[c[0] for c in CASES_EXPECT])
async def test_expect_needs_fresh_unnegated_evidence(base, engine, case):  # noqa: F811
    bm, sess = await _session(base, engine)
    try:
        status, out = await run_expect_case(sess, base, case)
    finally:
        await bm.close()
    cls = classify(case[6], status)
    assert cls != "SETUP_ERROR", f"{case[0]} on {engine}: the case never ran\n{out}"
    assert cls != "FALSE_VERIFIED", f"{case[0]} ({case[7]}) on {engine}: claimed verified\n{out}"
    if case[6]:
        assert cls == "true_verified", f"{case[0]} ({case[7]}) on {engine}: status {status}\n{out}"


# ---------- outcome words in other languages (pure regex, no browser) ----------
from lean_browser.session import ERROR_RE, NEGATED_SUCCESS_RE, SUCCESS_RE  # noqa: E402


def _is_success(t: str) -> bool:
    """The rule _signals applies: a success word, and no error word or negated success anywhere in the text."""
    return bool(SUCCESS_RE.search(t)) and not ERROR_RE.search(t) and not NEGATED_SUCCESS_RE.search(t)


SUCCESS_TEXTS = [
    "Changes saved.", "Thank you, your order is placed", "Order no. 5 confirmed", "Booking no 4411 confirmed",
    "Ihre Änderungen wurden gespeichert.", "Vielen Dank für Ihre Bestellung", "Erfolgreich gesendet",
    "Enregistré avec succès", "Merci pour votre commande", "Message envoyé",
    "Salvato correttamente", "Grazie!", "Ordine completato",
    "Guardado con éxito", "¡Gracias por tu compra!", "Pedido confirmado",
    "Salvo com sucesso", "Obrigado!", "Pedido concluído",
    "Сохранено", "Успешно отправлено", "Спасибо за заказ",
    "保存成功", "已保存", "谢谢",
    "保存しました", "送信が完了しました", "ありがとうございます",
    "저장되었습니다", "완료", "감사합니다",
    "सफलतापूर्वक सहेजा गया", "धन्यवाद", "भुगतान सफल",
]
NEGATED_TEXTS = [
    "Your changes were not saved.", "Message wasn't sent", "unsuccessful",
    "Nicht gespeichert", "Die Änderung konnte nicht gespeichert werden.", "Keine Änderungen gespeichert", "Erfolglos",
    "Non enregistré", "Votre message n'a pas été envoyé", "Sans succès",
    "Non salvato", "Senza successo",
    "No guardado", "No se ha guardado", "Sin éxito",
    "Não foi salvo", "Sem sucesso",
    "Не сохранено", "Не успешно",
    "未保存", "没有保存", "不成功",
    "保存されていません", "保存できませんでした",
    "저장되지 않았습니다", "저장하지 못했습니다",
    "सहेजा नहीं गया", "भुगतान असफल",
]
BOTH_TEXTS = ["Gespeichert, aber Fehler beim Senden", "保存成功，但发送失败", "Enregistré, mais erreur d'envoi",
              "Saved, but an error occurred"]
NEITHER_TEXTS = ["Merci de saisir votre e-mail", "Confirme ton adresse e-mail", "Create account", "Speichern",
                 "Guardar", "保存", "저장", "Todos los campos son obligatorios salvo el teléfono"]


@pytest.mark.parametrize("text", SUCCESS_TEXTS)
def test_success_words_in_many_languages(text):
    assert _is_success(text), text


@pytest.mark.parametrize("text", NEGATED_TEXTS)
def test_negated_success_counts_as_error_never_success(text):
    assert not _is_success(text), text
    assert NEGATED_SUCCESS_RE.search(text) or ERROR_RE.search(text), text


@pytest.mark.parametrize("text", BOTH_TEXTS)
def test_success_and_error_together_is_not_success(text):
    assert SUCCESS_RE.search(text) and ERROR_RE.search(text), text
    assert not _is_success(text), text


@pytest.mark.parametrize("text", NEITHER_TEXTS)
def test_instructions_and_labels_are_not_success(text):
    assert not _is_success(text), text


def test_hindi_words_match_despite_vowel_signs():
    # Devanagari vowel signs are not \w in Python, so a plain \b after "त्रुटि" never matched before.
    assert ERROR_RE.search("त्रुटि हुई") and ERROR_RE.search("त्रुटि")
    assert not SUCCESS_RE.search("असफल")  # "unsuccessful" contains सफल but is not success
