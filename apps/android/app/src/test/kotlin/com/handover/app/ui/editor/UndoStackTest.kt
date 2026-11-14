package com.handover.app.ui.editor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UndoStackTest {
    @Test fun undoThenRedoWalksBackAndForth() {
        val s = UndoStack<String>()
        s.push("a")      // a -> b
        s.push("b")      // b -> c
        assertEquals("b", s.undo("c"))
        assertEquals("a", s.undo("b"))
        assertNull(s.undo("a"))
        assertEquals("b", s.redo("a"))
        assertEquals("c", s.redo("b"))
        assertNull(s.redo("c"))
    }

    @Test fun aNewChangeClearsRedo() {
        val s = UndoStack<Int>()
        s.push(1)
        assertEquals(1, s.undo(2))
        assertTrue(s.canRedo)
        s.push(1)
        assertFalse(s.canRedo)
    }

    @Test fun keepsOnlyTheNewestEntries() {
        val s = UndoStack<Int>(limit = 3)
        (1..5).forEach { s.push(it) }
        assertEquals(3, s.undoCount)
        assertEquals(5, s.undo(6))
        assertEquals(4, s.undo(5))
        assertEquals(3, s.undo(4))
        assertNull(s.undo(3))
    }

    @Test fun dropLastForgetsARefusedChange() {
        val s = UndoStack<Int>()
        s.push(1); s.push(2)
        s.dropLast()
        assertEquals(1, s.undo(3))
    }
}
