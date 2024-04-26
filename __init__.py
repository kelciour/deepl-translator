import os
import re
import sys
import time
import warnings

from anki.hooks import addHook
from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo, showWarning, tooltip
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from . import lang

try:
    from . import form_qt6 as form
except:
    from . import form_qt5 as form

warnings.filterwarnings('ignore', category=MarkupResemblesLocatorWarning)


addon_dir = os.path.dirname(os.path.realpath(__file__))
vendor_dir = os.path.join(addon_dir, "vendor")
sys.path.append(vendor_dir)

import deepl


class DeepLTranslator(QDialog):
    def __init__(self, context, nids=None) -> None:
        if nids is None:
            self.editor = context
            self.browser = None
            self.parentWindow = self.editor.parentWindow
            self.note = self.editor.note
            self.nids = [None]
        else:
            self.editor = None
            self.browser = context
            self.parentWindow = self.browser
            self.note = None
            self.nids = nids
        self.total_count = 0
        self.exception = None
        self.translator = None

        QDialog.__init__(self, self.parentWindow)

        self.icon = os.path.join(os.path.dirname(__file__), "favicon.png")
        self.setWindowIcon(QIcon(self.icon))

        self.config = mw.addonManager.getConfig(__name__)
        self.api_key = self.config["API Key"]

        self.sourceLanguages = {}
        for x in lang.source_languages:
            assert x["name"] not in self.sourceLanguages, x["name"]
            self.sourceLanguages[x["name"]] = x["code"]

        self.targetLanguages = {}
        for x in lang.target_languages:
            assert x["name"] not in self.targetLanguages, x["name"]
            self.targetLanguages[x["name"]] = x["code"]

        if self.editor and self.config["~ Don't show dialog box in editor"] and self.api_key and \
            self.config["Source Field"] in self.note and self.config["Target Field"] in self.note:
            self.translate()
        else:
            self.setupUI()
            self.show()

    def setupUI(self):
        self.form = form.Ui_Dialog()
        self.form.setupUi(self)

        self.form.sourceLang.addItems(self.sourceLanguages)

        self.form.targetLang.addItems(self.targetLanguages)
        self.form.targetLang.setCurrentIndex(
            list(self.targetLanguages).index("English (American)")
        )

        def getLangCode(combobox, languages):
            text = combobox.currentText()
            if not text:
                return "##"
            return languages[text]

        def updateTargetLang():
            self.sourceLangCode = getLangCode(
                self.form.sourceLang, self.sourceLanguages
            )
            self.targetLangCode = getLangCode(
                self.form.targetLang, self.targetLanguages
            )
            if self.targetLangCode.startswith(self.sourceLangCode):
                self.form.targetLang.blockSignals(True)
                self.form.targetLang.setCurrentIndex(-1)
                self.form.targetLang.blockSignals(False)

        def updateSourceLang():
            self.sourceLangCode = getLangCode(
                self.form.sourceLang, self.sourceLanguages
            )
            self.targetLangCode = getLangCode(
                self.form.targetLang, self.targetLanguages
            )
            if self.targetLangCode.startswith(self.sourceLangCode):
                self.form.sourceLang.blockSignals(True)
                self.form.sourceLang.setCurrentIndex(0)
                self.form.sourceLang.blockSignals(False)

        self.form.sourceLang.currentIndexChanged.connect(updateTargetLang)
        self.form.targetLang.currentIndexChanged.connect(updateSourceLang)

        if not self.note:
            self.note = mw.col.getNote(self.nids[0])
        fields = self.note.keys()

        self.form.sourceField.addItems(fields)
        self.form.sourceField.setCurrentIndex(0)

        self.form.targetField.addItems(fields)
        self.form.targetField.setCurrentIndex(len(fields) - 1)

        for fld, cb in [
            ("Source Field", self.form.sourceField),
            ("Target Field", self.form.targetField),
        ]:
            if self.config[fld] and self.config[fld] in self.note:
                cb.setCurrentIndex(fields.index(self.config[fld]))

        for key, cb in [
            ("Source Language", self.form.sourceLang),
            ("Target Language", self.form.targetLang),
        ]:
            if self.config[key]:
                cb.setCurrentIndex(cb.findText(self.config[key]))

        if self.config["Strip HTML"]:
            self.form.formatText.setChecked(True)
        else:
            self.form.formatHTML.setChecked(True)

        self.form.checkBoxOverwrite.setChecked(self.config["Overwrite"])

        self.form.checkBoxDialogVisibility.setChecked(self.config["~ Don't show dialog box in editor"])
        if self.browser and self.config["~ Don't show dialog box in editor"] == False:
            self.form.checkBoxDialogVisibility.hide()

        self.form.apiKey.setText(self.api_key)

        self.usage = None

        if self.api_key:
            try:
                self.form.apiKeyBox.hide()
                self.adjustSize()
                if self.browser:
                    self.translator = deepl.Translator(self.api_key, skip_language_check=True)
                    self.usage = self.translator.get_usage()
            except Exception as e:
                pass

        if self.usage:
            self.usage.character.limit_exceeded
            self.form.usage.setText(
                "Usage: {}/{}".format(
                    self.usage.character.count, self.usage.character.limit
                )
            )
        else:
            self.form.usage.setText("")

    def sleep(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(0.01)
            QApplication.instance().processEvents()

    def escape_clozes(self, match):
        self.cloze_id += 1
        cloze_number = match.group('number')
        cloze_text = match.group('text')
        cloze_hint = match.group('hint')
        self.cloze_deletions[self.cloze_id] = {
            'number': cloze_number,
            'hint': cloze_hint
        }
        return ' <c{0}>{1}</c{0}> '.format(self.cloze_id, cloze_text)

    def unescape_clozes(self, match):
        cloze = self.cloze_deletions[int(match.group('id'))]
        txt = '{{'
        txt += 'c{}::{}'.format(cloze['number'], match.group('text'))
        if cloze['hint']:
            txt += '::{}'.format(cloze['hint'])
        txt += '}}'
        return txt

    def accept(self):
        self.sourceField = self.form.sourceField.currentText()
        self.targetField = self.form.targetField.currentText()

        self.config["Source Field"] = self.sourceField
        self.config["Target Field"] = self.targetField

        self.sourceLang = self.form.sourceLang.currentText()
        self.targetLang = self.form.targetLang.currentText()

        self.api_key = self.form.apiKey.text().strip()

        if not self.targetLang:
            return showWarning("Select target language")

        if not self.api_key:
            return showWarning(
                "To use the add-on and translate up to 500,000 characters/month for free, "
                "you'll need an API authentication key. "
                'To get a key, <a href="https://www.deepl.com/pro#developer">create an account with the DeepL API Free plan here</a>.',
                title="DeepL Translator",
            )

        try:
            self.translator = deepl.Translator(self.api_key, skip_language_check=True)
            self.translator.get_usage()
            self.config["API Key"] = self.api_key
        except deepl.exceptions.AuthorizationException:
            showWarning(
                "Authorization failed, check your authentication key.",
                title="DeepL Translator",
            )
            self.form.apiKeyBox.show()
            return
        except:
            raise

        self.config["Source Language"] = self.sourceLang
        self.config["Target Language"] = self.targetLang
        self.config["Strip HTML"] = self.form.formatText.isChecked()
        self.config["Overwrite"] = self.form.checkBoxOverwrite.isChecked()
        self.config["~ Don't show dialog box in editor"] = self.form.checkBoxDialogVisibility.isChecked()

        mw.addonManager.writeConfig(__name__, self.config)

        QDialog.accept(self)

        self.translate()

    def translate(self):
        self.sourceField = self.config["Source Field"]
        self.targetField = self.config["Target Field"]

        self.sourceLang = self.config["Source Language"]
        self.targetLang = self.config["Target Language"]

        self.sourceLangCode = self.sourceLanguages[self.sourceLang]
        self.targetLangCode = self.targetLanguages[self.targetLang]

        self.translator = deepl.Translator(self.api_key, skip_language_check=True)

        if self.browser:
            self.browser.mw.progress.start(parent=self.browser)
            self.browser.mw.progress._win.setWindowIcon(QIcon(self.icon))
            self.browser.mw.progress._win.setWindowTitle("DeepL Translator")

        progress = 0

        exception = None
        try:
            for nid in self.nids:
                if self.editor:
                    note = self.note
                else:
                    note = mw.col.getNote(nid)

                if not note[self.sourceField]:
                    continue
                if self.sourceField not in note:
                    continue
                if self.targetField not in note:
                    continue
                if note[self.targetField] and not self.config["Overwrite"]:
                    if self.editor:
                        tooltip('The field is not empty.')
                    continue

                text = note[self.sourceField]
                text = re.sub(r'\[sound:.*?\]', '', text)
                if self.config["Strip HTML"]:
                    soup = BeautifulSoup(text, "html.parser")
                    text = soup.get_text()
                else:
                    text = text.replace('&nbsp;', ' ')
                    text = re.sub(r' +(</[^>]+>)', r'\1 ', text)
                text = re.sub(r'\s+', ' ', text)
                text = text.strip()

                if not text:
                    continue

                self.cloze_id = 0
                self.cloze_deletions = {}
                text = re.sub(r"{{c(?P<number>\d+)::(?P<text>.*?)(::(?P<hint>.*?))?}}", self.escape_clozes, text, flags=re.I)
                self.cloze_hints = [c['hint'] for c in self.cloze_deletions.values() if c['hint']]

                time_to_sleep = 1

                self.total_count += len(text)

                translated_results = {}
                for key, data in [("text", text), ("hints", self.cloze_hints)]:
                    if key == "hints" and len(self.cloze_hints) == 0:
                        break
                    while True:
                        if self.browser and self.browser.mw.progress._win.wantCancel:
                            break
                        try:
                            if self.sourceLangCode != "AUTO":
                                source_lang = self.sourceLangCode
                            else:
                                source_lang = None
                            target_lang = self.targetLangCode
                            if not self.config["Strip HTML"]:
                                tag_handling = "xml"
                            else:
                                tag_handling = None
                            result = self.translator.translate_text(
                                data,
                                source_lang=source_lang,
                                target_lang=target_lang,
                                tag_handling=tag_handling,
                                split_sentences="nonewlines",
                                outline_detection=True,
                                ignore_tags=["sub", "sup"],
                            )
                            translated_results[key] = result
                            break
                        except deepl.exceptions.TooManyRequestsException:
                            if self.browser:
                                self.browser.mw.progress.update(
                                    "Too many requests. Sleeping for {} seconds.".format(
                                        time_to_sleep
                                    )
                                )
                                self.sleep(time_to_sleep)
                                # https://support.deepl.com/hc/en-us/articles/360020710619-Error-code-429
                                time_to_sleep *= 2
                            else:
                                showWarning(
                                    "Too many requests. Please wait and resend your request.",
                                    parent=self.parentWindow,
                                )

                if self.cloze_hints:
                    cloze_hints_translated = [tr.text for tr in translated_results["hints"]]
                    assert len(self.cloze_hints) == len(cloze_hints_translated)
                    hint_idx = 0
                    for c in self.cloze_deletions.values():
                        if c['hint']:
                            c['hint'] = cloze_hints_translated[hint_idx]
                            hint_idx += 1

                text = translated_results["text"].text

                text = re.sub(r' (<c\d+>) ', r' \1', text)
                text = re.sub(r' (</c\d+>) ', r'\1 ', text)
                text = re.sub(r'<c(?P<id>\d+)>(?P<text>.*?)</c(?P=id)>', self.unescape_clozes, text)
                text = re.sub(r' , ', ', ', text)

                note[self.targetField] = text

                if self.editor:
                    self.editor.setNote(note)
                else:
                    note.flush()

                progress += 1

                if self.browser:
                    self.browser.mw.progress.update(
                        "Processed {}/{} notes...".format(progress, len(self.nids))
                    )
                    QApplication.instance().processEvents()
        except Exception as e:
            exception = e
        finally:
            if self.browser:
                self.browser.mw.progress.finish()
                self.browser.mw.reset()
                mw.col.save()

        if exception:
            try:
                raise exception
            except deepl.exceptions.QuotaExceededException:
                showWarning(
                    "Quota for this billing period has been exceeded.",
                    parent=self.parentWindow,
                )
        else:
            if self.browser:
                showInfo(
                    "Processed {} notes.".format(len(self.nids)),
                    parent=self.browser,
                )


def onDeepLTranslator(browser):
    nids = browser.selectedNotes()

    if not nids:
        return tooltip("No cards selected.")

    DeepLTranslator(browser, nids)


def setupMenu(browser):
    a = QAction("DeepL Translator", browser)
    a.triggered.connect(lambda: onDeepLTranslator(browser))
    browser.form.menuEdit.addSeparator()
    browser.form.menuEdit.addAction(a)


addHook("browser.setupMenus", setupMenu)


def onEditorButton(editor):
    DeepLTranslator(editor)
    return None


def onSetupEditorButtons(buttons, editor):
    icon = os.path.join(os.path.dirname(__file__), "favicon.png")
    b = editor.addButton(
        icon,
        "DeepL Translator",
        lambda e=editor: onEditorButton(e),
        tip="{}".format("DeepL Translator"),
    )
    buttons.append(b)
    return buttons


from aqt.gui_hooks import editor_did_init_buttons

editor_did_init_buttons.append(onSetupEditorButtons)
