from django.urls import path

from . import views

app_name = "api"

P = "projects/<str:key>/"
I = P + "issues/<int:number>/"

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("markdown-preview/", views.MarkdownPreviewView.as_view(), name="markdown_preview"),
    path("projects/", views.ProjectListView.as_view(), name="projects"),
    path("issues/", views.IssueSearchView.as_view(), name="issue_search"),
    path(P, views.ProjectDetailView.as_view(), name="project"),
    path(P + "issues/", views.IssueListCreateView.as_view(), name="issues"),
    path(I, views.IssueDetailView.as_view(), name="issue"),
    path(I + "transition/", views.IssueTransitionView.as_view(), name="issue_transition"),
    path(I + "move/", views.IssueMoveView.as_view(), name="issue_move"),
    path(I + "comments/", views.CommentListCreateView.as_view(), name="issue_comments"),
    path(P + "sprints/", views.SprintListCreateView.as_view(), name="sprints"),
    path(P + "sprints/<int:pk>/", views.SprintDetailView.as_view(), name="sprint"),
    path(P + "sprints/<int:pk>/start/", views.SprintStartView.as_view(), name="sprint_start"),
    path(P + "sprints/<int:pk>/complete/", views.SprintCompleteView.as_view(), name="sprint_complete"),
    path(P + "sprints/<int:pk>/burndown/", views.SprintBurndownView.as_view(), name="sprint_burndown"),
    path(P + "velocity/", views.VelocityView.as_view(), name="velocity"),
    path(P + "test-runs/<int:pk>/", views.TestRunUpdateView.as_view(), name="test_run"),
    path(P + "test-executions/", views.TestExecutionListCreateView.as_view(), name="test_executions"),
    path(P + "test-executions/<int:pk>/", views.TestExecutionDetailView.as_view(), name="test_execution"),
    path(I + "links/", views.IssueLinkCreateView.as_view(), name="issue_links"),
    path(P + "coverage/", views.CoverageView.as_view(), name="coverage"),
]
