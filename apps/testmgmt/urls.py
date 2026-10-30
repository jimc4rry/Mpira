from django.urls import path

from . import views

app_name = "testmgmt"

urlpatterns = [
    path("<str:key>/issues/<int:number>/steps/", views.test_steps, name="test_steps"),
    path("<str:key>/tests/plans/", views.plan_list, name="plan_list"),
    path("<str:key>/tests/plans/new/", views.plan_form, name="plan_create"),
    path("<str:key>/tests/plans/<int:pk>/", views.plan_detail, name="plan_detail"),
    path("<str:key>/tests/plans/<int:pk>/edit/", views.plan_form, name="plan_edit"),
    path("<str:key>/tests/executions/", views.execution_list, name="execution_list"),
    path("<str:key>/tests/executions/new/", views.execution_create, name="execution_create"),
    path("<str:key>/tests/executions/<int:pk>/", views.execution_detail, name="execution_detail"),
    path("<str:key>/tests/executions/<int:pk>/delete/", views.execution_delete, name="execution_delete"),
    path("<str:key>/tests/executions/<int:pk>/run/", views.execution_run_queue, name="execution_run_queue"),
    path("<str:key>/tests/runs/<int:pk>/", views.run_update, name="run_update"),
    path("<str:key>/tests/coverage/", views.coverage, name="coverage"),
]
