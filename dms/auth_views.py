from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView


class DMSLoginView(LoginView):
    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Sie sind angemeldet.')
        return response


class DMSLogoutView(LogoutView):
    next_page = 'home'

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, 'Sie wurden abgemeldet.')
        return response
