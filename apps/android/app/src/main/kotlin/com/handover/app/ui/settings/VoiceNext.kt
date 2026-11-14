package com.handover.app.ui.settings

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/** "next" or "back", heard while a lesson is open. */
enum class VoiceCommand {
    Next, Back;

    companion object {
        private val next = setOf("next", "next step", "done", "go on")
        private val back = setOf("back", "go back", "previous")

        /**
         * The command in one recognized phrase, or null. Only short phrases count, so "I think the
         * next part is hard" does not move the lesson.
         */
        fun match(phrase: String): VoiceCommand? {
            val words = phrase.lowercase().replace(Regex("[^a-z ]"), " ").split(' ').filter(String::isNotBlank)
            if (words.isEmpty() || words.size > 3) return null
            val text = words.joinToString(" ")
            return when {
                text in next || words.last() == "next" -> Next
                text in back || words.last() == "back" -> Back
                else -> null
            }
        }
    }
}

/**
 * Listens for [VoiceCommand]s with the phone's SpeechRecognizer and keeps listening until [stop].
 * Learn starts it only while Voice Next is on and pauses it while the expert's clip is audible
 * (DESIGN.md 5). Needs the RECORD_AUDIO permission; call [isAvailable] first.
 */
class VoiceNextListener(private val context: Context, private val onCommand: (VoiceCommand) -> Unit) {
    private var recognizer: SpeechRecognizer? = null
    private var running = false

    fun start() {
        if (running || !isAvailable(context)) return
        running = true
        recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply { setRecognitionListener(listener) }
        listen()
    }

    fun stop() {
        running = false
        recognizer?.destroy()
        recognizer = null
    }

    private fun listen() {
        if (!running) return
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        recognizer?.startListening(intent)
    }

    private val listener = object : RecognitionListener {
        private var firedThisTurn = false

        override fun onReadyForSpeech(params: Bundle?) { firedThisTurn = false }
        override fun onPartialResults(partialResults: Bundle?) = handle(partialResults)
        override fun onResults(results: Bundle?) { handle(results); listen() }
        override fun onError(error: Int) { listen() }
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}
        override fun onEvent(eventType: Int, params: Bundle?) {}

        private fun handle(bundle: Bundle?) {
            if (firedThisTurn) return
            val heard = bundle?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
            val command = heard.firstNotNullOfOrNull { VoiceCommand.match(it) } ?: return
            firedThisTurn = true
            onCommand(command)
        }
    }

    companion object {
        fun isAvailable(context: Context): Boolean = SpeechRecognizer.isRecognitionAvailable(context)
    }
}
