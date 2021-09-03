import os
import re
import sys
import time

from anki.hooks import addHook
from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo, showWarning, tooltip
from bs4 import BeautifulSoup
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QDialog

from . import form, lang


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

        self.form = form.Ui_Dialog()
        self.form.setupUi(self)

        self.sourceLanguages = {}
        for x in lang.source_languages:
            assert x["name"] not in self.sourceLanguages, x["name"]
            self.sourceLanguages[x["name"]] = x["code"]

        self.targetLanguages = {}
        for x in lang.target_languages:
            assert x["name"] not in self.targetLanguages, x["name"]
            self.targetLanguages[x["name"]] = x["code"]

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
            self.note = mw.col.getNote(nids[0])
        fields = self.note.keys()

        self.form.sourceField.addItems(fields)
        self.form.sourceField.setCurrentIndex(0)

        self.form.targetField.addItems(fields)
        self.form.targetField.setCurrentIndex(len(fields) - 1)

        self.config = mw.addonManager.getConfig(__name__)

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

        self.form.checkBoxOverwrite.setChecked(self.config["Overwrite"])

        self.api_key = self.config["API Key"]

        self.form.apiKey.setText(self.api_key)

        self.usage = None

        if self.api_key:
            try:
                self.form.apiKeyBox.hide()
                self.adjustSize()
                self.translator = deepl.Translator(self.api_key)
                if self.browser:
                    self.usage = self.translator.get_usage()
            except Exception as e:
                pass

        self.icon = os.path.join(os.path.dirname(__file__), "favicon.png")
        self.setWindowIcon(QIcon(self.icon))

        if self.usage:
            self.usage.character.limit_exceeded
            self.form.usage.setText(
                "Usage: {}/{}".format(
                    self.usage.character.count, self.usage.character.limit
                )
            )
        else:
            self.form.usage.setText("")

        self.show()

    def sleep(self, seconds):
        start = time.time()
        while time.time() - start < seconds:
            time.sleep(0.01)
            QApplication.instance().processEvents()

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
                "To use the add-on, you'll need an API authentication key (DeepL API Free). "
                "To get a key and translate up to 500,000 characters/month for free, "
                '<a href="https://www.deepl.com/pro#developer">create a DeepL Pro account here</a>.',
                title="DeepL Translator",
            )

        try:
            self.translator = deepl.Translator(self.api_key)
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

        QDialog.accept(self)

        self.config["Source Language"] = self.sourceLang
        self.config["Target Language"] = self.targetLang

        self.config["Overwrite"] = self.form.checkBoxOverwrite.isChecked()

        mw.addonManager.writeConfig(__name__, self.config)

        self.sourceLangCode = self.sourceLanguages[self.sourceLang]
        self.targetLangCode = self.targetLanguages[self.targetLang]

        if self.browser:
            self.browser.mw.progress.start(parent=self.browser)
            self.browser.mw.progress._win.setWindowIcon(QIcon(self.icon))
            self.browser.mw.progress._win.setWindowTitle("Deepl Translator")

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
                    continue

                soup = BeautifulSoup(note[self.sourceField], "html.parser")

                text = soup.get_text()

                text = re.sub(
                    r"{{c(\d+)::(.*?)(::.*?)?}}", r"<c\1>\2</c>", text, flags=re.I
                )

                time_to_sleep = 1

                self.total_count += len(text)

                while True:
                    if self.browser and self.browser.mw.progress._win.wantCancel:
                        break
                    try:
                        if self.sourceLangCode == "AUTO":
                            result = self.translator.translate_text(
                                text, target_lang=self.targetLangCode
                            )
                        else:
                            result = self.translator.translate_text(
                                text,
                                source_lang=self.sourceLangCode,
                                target_lang=self.targetLangCode,
                            )
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

                note[self.targetField] = result.text

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


def onSetupEditorButtons(buttons, editor):
    icon = os.path.join(os.path.dirname(__file__), "favicon.png")
    b = editor.addButton(
        icon,
        "DeepL Translator",
        lambda e=editor: DeepLTranslator(e),
        tip="{}".format("DeepL Translator"),
    )
    buttons.append(b)
    return buttons


from aqt.gui_hooks import editor_did_init_buttons

editor_did_init_buttons.append(onSetupEditorButtons)
