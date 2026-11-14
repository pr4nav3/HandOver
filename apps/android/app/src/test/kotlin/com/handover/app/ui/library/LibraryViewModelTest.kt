package com.handover.app.ui.library

import com.handover.app.core.HubException
import com.handover.app.core.LessonSummary
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class LibraryViewModelTest {
    @get:Rule val main = MainDispatcherRule()

    private fun summary(id: String, title: String = id, status: String = "published", progress: CourseProgress? = null, cover: String? = null) =
        CourseSummary(id = id, title = title, steps = 8, duration = 192.0, status = status, progress = progress, coverUrl = cover)

    @Test fun legacyHubFallsBackToLessonsWithoutFilters() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { lessonsResult = listOf(LessonSummary("fold", "Fold a fortune teller", 8)) }
        val vm = LibraryViewModel(b)
        advanceUntilIdle()
        val s = vm.state.value
        assertTrue(s.legacy)
        assertEquals(listOf("fold"), s.items.map { it.id })
        assertTrue("no accounts: no filter row", s.filters.isEmpty())
        assertEquals(listOf("http://hub/lessons/fold/produced/cover.jpg", "http://hub/lessons/fold/frames/01.jpg"), s.items[0].covers)
        assertNull(s.items[0].duration)
    }

    @Test fun coursesCarryBadgesCoversAndContinue() = runTest(main.dispatcher) {
        val b = FakeBackend().apply {
            meResult = Me("u1", "Sam", "teacher", "optional")
            coursesResult = { _, _ ->
                listOf(
                    summary("a", status = "draft", cover = "/lessons/a/covers/c.jpg"),
                    summary("b", progress = CourseProgress(known = true, lastStepsDone = 3, total = 8)),
                    summary("c", progress = CourseProgress(known = true, lastStepsDone = 8, lastFinished = true, completed = 1)),
                )
            }
        }
        val vm = LibraryViewModel(b)
        advanceUntilIdle()
        val s = vm.state.value
        assertFalse(s.legacy)
        assertEquals("Draft", s.items[0].badge)
        assertEquals("http://hub/lessons/a/covers/c.jpg", s.items[0].covers.first())
        assertEquals(listOf("b" to 3), s.continueItems.map { it.first.id to it.second })
        assertTrue(s.items[2].completed)
        assertEquals(listOf("Everyone", "Mine", "Shared with Me"), s.filters.map { it.label })
    }

    @Test fun liveSessionComesFirstInContinue() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { lessonsResult = listOf(LessonSummary("x", "X", 5), LessonSummary("y", "Y", 5)) }
        val vm = LibraryViewModel(b)
        advanceUntilIdle()
        vm.setSession("y", 2, 5, done = false)
        assertEquals(listOf("y" to 2), vm.state.value.continueItems.map { it.first.id to it.second })
        vm.setSession("y", 2, 5, done = true)
        assertTrue(vm.state.value.continueItems.isEmpty())
    }

    @Test fun orgFiltersAppearAndQueryTheOrg() = runTest(main.dispatcher) {
        val b = FakeBackend().apply {
            meResult = Me("u1", "Sam", "teacher", "optional")
            orgsResult = listOf(Org("o1", "Makerspace", 12, "learner"))
            coursesResult = { _, org -> if (org == "o1") listOf(summary("org-lesson")) else listOf(summary("a")) }
        }
        val vm = LibraryViewModel(b)
        advanceUntilIdle()
        assertEquals(listOf("Everyone", "Mine", "Shared with Me", "My Orgs", "Makerspace"), vm.state.value.filters.map { it.label })
        vm.setFilter(LibraryFilter.MyOrgs)
        advanceUntilIdle()
        assertTrue("courses:orgs:" in b.calls)
        val orgFilter = vm.state.value.filters.last()
        vm.setFilter(orgFilter)
        advanceUntilIdle()
        assertEquals(listOf("org-lesson"), vm.state.value.items.map { it.id })
        assertTrue("courses:all:o1" in b.calls)
    }

    @Test fun searchFiltersLocallyAndHidesContinue() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { lessonsResult = listOf(LessonSummary("a", "Fold a crane", 3), LessonSummary("b", "Change a tire", 4)) }
        val vm = LibraryViewModel(b)
        advanceUntilIdle()
        vm.setSession("b", 1, 4, false)
        vm.setQuery("CRANE")
        assertEquals(listOf("a"), vm.state.value.items.map { it.id })
        assertTrue(vm.state.value.continueItems.isEmpty())
    }

    @Test fun hubErrorIsPlainWords() = runTest(main.dispatcher) {
        val b = object : FakeBackend() {
            override suspend fun lessons(): List<LessonSummary> = throw java.io.IOException("refused")
        }
        val vm = LibraryViewModel(b)
        advanceUntilIdle()
        assertEquals("Could not reach the hub. Check that it is running and on the same Wi-Fi.", vm.state.value.error)
    }

    @Test fun missingRouteIsNotFoundDetailOnly() {
        assertTrue(isMissingRoute(HubException(404, "Not Found")))
        assertFalse(isMissingRoute(HubException(404, "lesson not found")))
        assertTrue(isMissingRoute(HubException(405, "Method Not Allowed")))
    }

    @Test fun formats() {
        assertEquals("8 steps, 3:12", stepsMeta(8, 192.0))
        assertEquals("1 step", stepsMeta(1, null))
        assertEquals("1:02:05", clock(3725.0))
        assertEquals("This video is over 2 GB. Trim it or record a shorter take.", HubException(413, "video is larger than 2 GB").plainWords())
        assertEquals("The hub is busy with other lessons. Try again when one finishes.", HubException(429, "too many jobs").plainWords())
    }
}
