from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema
from rest_framework import pagination, status, views
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from src.accounts_app.serializers import RegisterSerializer, UserSerializer
from src.utils.logs import Logger
from src.utils.permissions import IsAdmin


class UserPagination(pagination.PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class RegisterView(views.APIView):
    # Open sign-up; a stale token header must not block it.
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        Logger.info(
            "User registered",
            user_id=user.pk,
            username=user.username,
        )
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class LogoutView(views.APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        # The token is shared by all of the user's sessions; all end.
        Token.objects.filter(user=request.user).delete()
        Logger.info("User logged out", user_id=request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListView(views.APIView):
    permission_classes = [IsAdmin]
    serializer_class = UserSerializer

    def get(self, request):
        queryset = User.objects.order_by("id")
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(username__icontains=search)
        paginator = UserPagination()
        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )
        serializer = UserSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class UserDetailView(views.APIView):
    permission_classes = [IsAdmin]
    serializer_class = UserSerializer

    def get(self, request, user_id):
        return Response(UserSerializer(self._get(user_id)).data)

    def patch(self, request, user_id):
        user = self._get(user_id)
        if user.pk == request.user.pk:
            Logger.warning("Admin tried to change own role", user_id=user_id)
            return self._self_conflict()
        serializer = UserSerializer(
            user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        Logger.info(
            "User updated",
            user_id=user_id,
            by=request.user.pk,
            fields=list(request.data),
        )
        return Response(serializer.data)

    def delete(self, request, user_id):
        user = self._get(user_id)
        if user.pk == request.user.pk:
            Logger.warning("Admin tried to delete self", user_id=user_id)
            return self._self_conflict()
        user.delete()
        Logger.info(
            "User deleted",
            user_id=user_id,
            by=request.user.pk,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _get(user_id):
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            raise NotFound()
        return user

    @staticmethod
    def _self_conflict():
        # Keeps at least one admin: nobody demotes or deletes themselves.
        return Response(
            {"detail": "You can't change your own role or delete yourself."},
            status=status.HTTP_409_CONFLICT,
        )
