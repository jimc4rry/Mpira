from django.contrib import admin

from .models import TestExecution, TestPlan, TestRun, TestStep

admin.site.register([TestStep, TestPlan, TestExecution, TestRun])
