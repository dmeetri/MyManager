import hashlib
import mimetypes
import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

# Формируем стабильный путь по UUID документа, чтобы имена файлов не конфликтовали
def document_upload_path(instance, filename):
    return f"documents/{instance.uuid}/{filename}"


# Подразделение / организация, к которой относится документ
class Department(models.Model):
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    def __str__(self):
        return self.name


# Тип документа: рапорт, дефектный акт, приказ и т.д.
# Дерево нужно, чтобы группировать типы по разделам
class DocumentCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# Категория тега: "формат", "тема", "проект" и т.п.
# Нужна, чтобы отделять теги формата (pdf/excel/word/image) от смысловых
class TagCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# Тег для поиска: pdf, excel, word, image, "отчётность", "2024" и т.п.
class Tag(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, blank=True)
    category = models.ForeignKey(
        TagCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tags",
    )

    class Meta:
        unique_together = ("name", "category")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# Сам документ
class Document(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ACTIVE = "active", "Действующий"
        ARCHIVED = "archived", "В архиве"
        SUPERSEDED = "superseded", "Заменён"

    # Уровень доступа
    class Confidentiality(models.TextChoices):
        PUBLIC = "public", "Публичный"
        INTERNAL = "internal", "Внутренний"
        CONFIDENTIAL = "confidential", "Конфиденциальный"
        SECRET = "secret", "Секретный"

    # UUID отдельно от pk — для стабильных путей к файлам
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # --- Реквизиты документа ---
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    document_number = models.CharField(max_length=100, blank=True)
    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )

    # --- Даты ---
    document_date = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Файл и его метаданные ---
    file = models.FileField(upload_to=document_upload_path)
    original_filename = models.CharField(max_length=500, blank=True)
    file_size = models.BigIntegerField(default=0)
    mime_type = models.CharField(max_length=255, blank=True)
    extension = models.CharField(max_length=20, blank=True, db_index=True)
    # SHA-256 для быстрого поиска дублей и контроля целостности
    checksum = models.CharField(max_length=64, blank=True, db_index=True)
    pages_count = models.PositiveIntegerField(null=True, blank=True)

    # --- Авторство и принадлежность ---
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_documents",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_documents",
    )
    # Автор как строка, т.к. это может быть внешний контрагент или подписант
    author = models.CharField(max_length=255, blank=True)
    signed_by = models.CharField(max_length=255, blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    # Источник появления (скан, ЭДО, email и т.п.)
    source = models.CharField(max_length=255, blank=True)

    # --- Состояние ---
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    confidentiality = models.CharField(
        max_length=20,
        choices=Confidentiality.choices,
        default=Confidentiality.INTERNAL,
    )
    language = models.CharField(max_length=10, blank=True)

    # --- Версионирование ---
    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True, db_index=True)
    previous_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_versions",
    )

    # --- Мягкое удаление с аудитом ---
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_documents",
    )
    deletion_reason = models.CharField(max_length=500, blank=True)

    # --- Хранение ---
    # Дата, после которой документ можно окончательно утилизировать
    retention_until = models.DateField(null=True, blank=True)

    # --- Связи ---
    tags = models.ManyToManyField(Tag, blank=True, related_name="documents")
    related_documents = models.ManyToManyField(
        "self",
        blank=True,
        symmetrical=False,
        related_name="related_to",
    )

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["category", "document_date"]),
            models.Index(fields=["status", "is_deleted"]),
            models.Index(fields=["department", "-uploaded_at"]),
        ]

    def save(self, *args, **kwargs):
        # Автозаполняем метаданные файла при каждом сохранении
        if self.file:
            self.original_filename = os.path.basename(self.file.name)
            self.extension = os.path.splitext(self.original_filename)[1].lower().lstrip(".")
            self.mime_type = mimetypes.guess_type(self.original_filename)[0] or ""
            self.file_size = getattr(self.file, "size", 0) or 0
            # Хеш считаем только при первой загрузке (файл мог не измениться)
            if not self.checksum:
                self.file.seek(0)
                hasher = hashlib.sha256()
                for chunk in self.file.chunks():
                    hasher.update(chunk)
                self.checksum = hasher.hexdigest()
                self.file.seek(0)
        # Автоматическая простановка/сброс даты удаления
        if self.is_deleted and not self.deleted_at:
            self.deleted_at = timezone.now()
        if not self.is_deleted:
            self.deleted_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
