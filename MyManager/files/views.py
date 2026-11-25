from django.views.generic import CreateView, ListView, DetailView, DeleteView, UpdateView

from . import models

# TODO
# Добавить декораторы для требования входа в систему

class CreateFileView(CreateView):
    pass


class ListFilesView(ListView):
    model = models.Document
    template_name = "files/list.html"
    context_object_name = "file"
    paginate_by = 20


class DetailFileView(DetailView):
    pass


class DeleteFilesView(DeleteView):
    pass


class UpdateFileView(UpdateView):
    pass
