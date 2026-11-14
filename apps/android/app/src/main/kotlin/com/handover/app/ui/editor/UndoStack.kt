package com.handover.app.ui.editor

/**
 * Undo and redo as two stacks of snapshots. Every change is one entry (SCREENS.md 14.4: "Every change is one
 * undo step"). A new change clears redo. Kept to [limit] entries so a long session cannot grow without bound.
 */
class UndoStack<T>(private val limit: Int = 100) {
    private val undo = ArrayDeque<T>()
    private val redo = ArrayDeque<T>()

    val canUndo: Boolean get() = undo.isNotEmpty()
    val canRedo: Boolean get() = redo.isNotEmpty()
    val undoCount: Int get() = undo.size
    val redoCount: Int get() = redo.size

    /** Records [before], the state a change is about to replace. */
    fun push(before: T) {
        undo.addLast(before)
        if (undo.size > limit) undo.removeFirst()
        redo.clear()
    }

    /** The state to go back to, with [current] kept for redo; null when there is nothing to undo. */
    fun undo(current: T): T? {
        val previous = undo.removeLastOrNull() ?: return null
        redo.addLast(current)
        return previous
    }

    fun redo(current: T): T? {
        val next = redo.removeLastOrNull() ?: return null
        undo.addLast(current)
        return next
    }

    /** Drops the newest undo entry, for a change the hub refused. */
    fun dropLast() {
        undo.removeLastOrNull()
    }

    fun clear() {
        undo.clear()
        redo.clear()
    }
}
