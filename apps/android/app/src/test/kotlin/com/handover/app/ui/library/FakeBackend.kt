package com.handover.app.ui.library

import com.handover.app.core.Lesson
import com.handover.app.core.LessonSummary
import com.handover.app.core.UploadResponse
import com.handover.app.core.UploadSource
import kotlinx.serialization.json.JsonObject

/** A [CourseBackend] for view model tests. Every call is recorded in [calls]; behavior is set per test. */
open class FakeBackend : CourseBackend {
    val calls = mutableListOf<String>()
    var meResult: Me? = null
    var coursesResult: ((String, String?) -> List<CourseSummary>?) = { _, _ -> null }
    var orgsResult: List<Org>? = null
    var lessonsResult: List<LessonSummary> = emptyList()
    var lessonResult: (String) -> Lesson = { Lesson(id = it) }
    var courseResult: CourseDetail? = null
    var texts: Map<String, String> = emptyMap()
    var uploadBlock: suspend (UploadSource, String, (Long, Long) -> Unit) -> UploadResponse = { v, _, p -> p(v.length, v.length); UploadResponse("job1", "lesson-1") }
    var jobs: ArrayDeque<() -> RawJob> = ArrayDeque()
    var editResult: (String) -> EditResult? = { null }
    var recutBodies = mutableListOf<JsonObject>()
    var recutResult: (JsonObject) -> Lesson = { Lesson() }

    override suspend fun me() = meResult.also { calls += "me" }
    override suspend fun courses(filter: String, query: String, org: String?) = coursesResult(filter, org).also { calls += "courses:$filter:${org ?: ""}" }
    override suspend fun orgs() = orgsResult.also { calls += "orgs" }
    override suspend fun lessons() = lessonsResult.also { calls += "lessons" }
    override suspend fun lesson(id: String) = lessonResult(id).also { calls += "lesson:$id" }
    override suspend fun lessonJson(id: String) = JsonObject(emptyMap()).also { calls += "lessonJson:$id" }
    override suspend fun course(id: String) = courseResult.also { calls += "course:$id" }
    override suspend fun ratings(id: String): RatingSummary? = null
    override suspend fun lessonText(lessonId: String, path: String, rev: Long) = texts[path]
    override fun fileUrl(lessonId: String, path: String, rev: Long) = "http://hub/lessons/$lessonId/$path"
    override fun absoluteUrl(path: String) = "http://hub$path"
    override suspend fun upload(video: UploadSource, title: String, onProgress: (Long, Long) -> Unit): UploadResponse {
        calls += "upload:$title"
        return uploadBlock(video, title, onProgress)
    }
    override suspend fun job(job: String): RawJob {
        calls += "job:$job"
        return (jobs.removeFirstOrNull() ?: { RawJob("done", "ready") })()
    }
    private fun edit(op: String) = editResult(op).also { calls += op }
    override suspend fun editBoundaries(id: String, edits: List<Triple<Int, String?, String?>>) = edit("boundaries:" + edits.joinToString(";") { "${it.first},${it.second},${it.third}" })
    override suspend fun editSplit(id: String, n: Int, at: String) = edit("split:$n:$at")
    override suspend fun editMerge(id: String, n: Int) = edit("merge:$n")
    override suspend fun editDelete(id: String, n: Int) = edit("delete:$n")
    override suspend fun editStep(id: String, n: Int, fields: Map<String, String>) = edit("step:$n:$fields")
    override suspend fun editCaptions(id: String, n: Int, cues: List<CueEdit>) = edit("captions:$n:${cues.size}")
    override suspend fun selfTest(id: String, n: Int): SelfTestResponse? = null.also { calls += "selftest:$n" }
    override suspend fun undo(id: String) = edit("undo")
    override suspend fun redo(id: String) = edit("redo")
    override suspend fun voiceover(id: String, steps: List<Int>): CourseJob? = null
    override suspend fun courseJob(id: String, job: String): CourseJob? = null
    override suspend fun publish(id: String, status: String, visibility: String?, org: String?): CourseInfo? =
        CourseInfo(id = id, status = status, visibility = visibility ?: "only_me", org = org?.let { OrgRef(it, it) }).also { calls += "publish:$status:${visibility ?: ""}:${org ?: ""}" }
    override suspend fun unpublish(id: String): CourseInfo? = null
    override suspend fun setVisibility(id: String, visibility: String): CourseInfo? = CourseInfo(id = id, visibility = visibility).also { calls += "visibility:$visibility" }
    override suspend fun recut(id: String, lesson: JsonObject): Lesson {
        calls += "recut"
        recutBodies += lesson
        return recutResult(lesson)
    }
}
