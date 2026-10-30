from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.agile.models import Sprint
from apps.issues.custom_fields import clean_custom_fields
from apps.issues.models import Comment, Issue, IssueType
from apps.projects.models import Component, Label, Project, Version
from apps.testmgmt.models import RunStatus, TestRun

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "username", "display_name", "role"]


class ProjectSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "key", "name", "description", "lead", "is_archived", "created_at", "members"]

    def get_members(self, obj):
        return [
            {"id": u.pk, "email": u.email, "username": u.username, "display_name": u.display_name}
            for u in obj.members_qs().order_by("username")
        ]


class IssueKeyField(serializers.CharField):
    """Accepts/returns issue keys like "MPR-12" for epic/parent references."""

    def to_representation(self, value):
        return value.key if value else None


class IssueSerializer(serializers.ModelSerializer):
    key = serializers.CharField(read_only=True)
    project = serializers.CharField(source="project.key", read_only=True)
    assignee = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), allow_null=True, required=False)
    reporter = serializers.PrimaryKeyRelatedField(read_only=True)
    epic = IssueKeyField(allow_null=True, required=False)
    parent = IssueKeyField(allow_null=True, required=False)
    sprint = serializers.PrimaryKeyRelatedField(queryset=Sprint.objects.all(), allow_null=True, required=False)
    labels = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=Label.objects.all())
    components = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Component.objects.all()
    )
    fix_versions = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Version.objects.all()
    )
    url = serializers.SerializerMethodField()
    assignee_name = serializers.SerializerMethodField()
    status_name = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = [
            "id",
            "key",
            "number",
            "project",
            "issue_type",
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "reporter",
            "epic",
            "parent",
            "sprint",
            "story_points",
            "due_date",
            "labels",
            "components",
            "fix_versions",
            "custom_fields",
            "rank",
            "created_at",
            "updated_at",
            "resolved_at",
            "url",
            "assignee_name",
            "status_name",
        ]
        read_only_fields = ["number", "status", "rank", "created_at", "updated_at", "resolved_at"]

    def get_url(self, obj):
        return obj.get_absolute_url()

    def get_assignee_name(self, obj):
        return obj.assignee.display_name if obj.assignee_id else None

    def get_status_name(self, obj):
        return obj.get_status_display()

    @property
    def project_obj(self):
        return self.context["project"]

    def _resolve_key(self, value, field):
        if value in (None, ""):
            return None
        project = self.project_obj
        try:
            pkey, number = str(value).upper().rsplit("-", 1)
            if pkey != project.key:
                raise ValueError
            return project.issues.get(number=int(number))
        except (ValueError, Issue.DoesNotExist):
            raise serializers.ValidationError({field: [f"No issue {value} in project {project.key}."]})

    def validate(self, attrs):
        project = self.project_obj
        instance = self.instance
        issue_type = attrs.get("issue_type", instance.issue_type if instance else IssueType.TASK)

        if "epic" in attrs:
            epic = self._resolve_key(attrs["epic"], "epic")
            if epic is not None and epic.issue_type != IssueType.EPIC:
                raise serializers.ValidationError({"epic": ["Must reference an Epic."]})
            attrs["epic"] = epic
        if "parent" in attrs:
            attrs["parent"] = self._resolve_key(attrs["parent"], "parent")
        parent = attrs.get("parent", instance.parent if instance else None)
        if issue_type == IssueType.SUBTASK and parent is None:
            raise serializers.ValidationError({"parent": ["A sub-task needs a parent issue."]})
        if issue_type != IssueType.SUBTASK:
            attrs["parent"] = None
        if parent is not None and instance is not None and parent.pk == instance.pk:
            raise serializers.ValidationError({"parent": ["An issue cannot be its own parent."]})

        assignee = attrs.get("assignee")
        if assignee is not None and not project.members_qs().filter(pk=assignee.pk).exists():
            raise serializers.ValidationError({"assignee": ["The assignee must be a member of the project."]})
        sprint = attrs.get("sprint")
        if sprint is not None and (sprint.project_id != project.pk or sprint.state == Sprint.State.CLOSED):
            raise serializers.ValidationError({"sprint": ["Must be an open sprint of this project."]})
        for field in ("labels", "components", "fix_versions"):
            for obj in attrs.get(field, []):
                if obj.project_id != project.pk:
                    raise serializers.ValidationError({field: [f"{obj} does not belong to this project."]})

        if "custom_fields" in attrs or "issue_type" in attrs or instance is None:
            raw = attrs.get("custom_fields", instance.custom_fields if instance else {})
            try:
                attrs["custom_fields"] = clean_custom_fields(project, issue_type, raw)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"custom_fields": exc.message_dict})
        return attrs


class TransitionSerializer(serializers.Serializer):
    status = serializers.CharField()


class MoveSerializer(serializers.Serializer):
    status = serializers.CharField(required=False)
    sprint = serializers.IntegerField(required=False, allow_null=True)
    before = serializers.IntegerField(required=False, allow_null=True, help_text="Issue number above the drop point")
    after = serializers.IntegerField(required=False, allow_null=True, help_text="Issue number below the drop point")


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "author", "body", "created_at", "updated_at"]
        read_only_fields = ["id", "author", "created_at", "updated_at"]

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("The comment cannot be empty.")
        return value


class SprintSerializer(serializers.ModelSerializer):
    committed_points = serializers.IntegerField(read_only=True)

    class Meta:
        model = Sprint
        fields = [
            "id",
            "name",
            "goal",
            "state",
            "start_date",
            "end_date",
            "started_at",
            "completed_at",
            "committed_points",
            "completed_points",
        ]
        read_only_fields = ["state", "started_at", "completed_at", "completed_points"]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": ["The end date must be after the start date."]})
        return attrs


class StartSprintSerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)


class CompleteSprintSerializer(serializers.Serializer):
    move_to = serializers.IntegerField(required=False, allow_null=True)


class TestRunSerializer(serializers.ModelSerializer):
    test = serializers.CharField(source="test.key", read_only=True)
    executed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    status = serializers.ChoiceField(choices=RunStatus.choices)

    class Meta:
        model = TestRun
        fields = ["id", "test", "status", "comment", "executed_by", "executed_at"]
        read_only_fields = ["id", "test", "executed_by", "executed_at"]

