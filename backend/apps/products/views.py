"""Product catalogue API views (spec §11.1).

Two resources with standard CRUD endpoints:

- ``/api/v1/products/`` - sellable items with current price and stock
- ``/api/v1/products/categories/`` - product groupings

Permissions are enforced through the role matrix (:mod:`apps.accounts.permissions`):
- ``CanViewProducts`` for list/retrieve (all staff roles)
- ``CanManageProducts`` for create/update/retire (Owner only)
- ``CanChangePrices`` for price changes and price history (Owner only)
- ``CanManageCategories`` for category CRUD (Owner only)

The role matrix is the authority. The prose above names the roles that hold
each capability today; if the matrix changes, these lines must change with it.

All list endpoints use :class:`apps.core.pagination.BarkotPagination` and return
the standard envelope: ``{count, page_size, page, pages, results}``.
"""

from django.db.models import Count
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    CanChangePrices,
    CanManageCategories,
    CanManageProducts,
    CanViewProducts,
)
from apps.core.pagination import BarkotPagination
from apps.core.query_params import boolean_value, positive_int
from apps.products.models import Category, Product
from apps.products.serializers import (
    CategoryCreateSerializer,
    CategorySerializer,
    CategoryUpdateSerializer,
    ProductCreateSerializer,
    ProductListSerializer,
    ProductPriceCreateSerializer,
    ProductPriceSerializer,
    ProductSerializer,
    ProductUpdateSerializer,
)
from apps.products.services import (
    create_category,
    create_product,
    delete_category,
    retire_product,
    set_product_price,
    update_category,
    update_product,
)


@extend_schema_view(
    list=extend_schema(
        summary="List categories",
        description="Paginated list of all categories. Requires ``products.view_products``.",
        tags=["products"],
    ),
    retrieve=extend_schema(
        summary="Get a category",
        description="Single category by ID. Requires ``products.view_products``.",
        tags=["products"],
    ),
    create=extend_schema(
        summary="Create a category",
        description=(
            "Create a new product category. Requires ``products.manage_categories`` (Owner)."
        ),
        tags=["products"],
    ),
    partial_update=extend_schema(
        summary="Update a category",
        description="Partially update a category. Requires ``products.manage_categories``.",
        tags=["products"],
    ),
    destroy=extend_schema(
        summary="Delete a category",
        description=(
            "Delete a category (only if no products reference it). "
            "Requires ``products.manage_categories``."
        ),
        tags=["products"],
    ),
)
class CategoryViewSet(viewsets.ModelViewSet):
    """CRUD for product categories.

    List/retrieve: ``CanViewProducts`` (all staff roles).
    Write: ``CanManageCategories`` (Owner only).
    """

    queryset = Category.objects.annotate(_product_count=Count("products")).order_by(
        "display_order", "name"
    )
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_serializer_class(self):
        if self.action == "create":
            return CategoryCreateSerializer
        if self.action in {"update", "partial_update"}:
            return CategoryUpdateSerializer
        return CategorySerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewProducts()]
        return [IsAuthenticated(), CanManageCategories()]

    def perform_create(self, serializer):
        serializer.instance = create_category(
            name=serializer.validated_data["name"],
            description=serializer.validated_data.get("description", ""),
            display_order=serializer.validated_data.get("display_order", 0),
            is_active=serializer.validated_data.get("is_active", True),
            actor=self.request.user,  # type: ignore[arg-type]
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Answer with the full category, including the id a client needs next."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        output = CategorySerializer(serializer.instance).data
        return Response(
            output,
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(output),
        )

    def perform_update(self, serializer):
        serializer.instance = update_category(
            category=self.get_object(),
            actor=self.request.user,  # type: ignore[arg-type]
            **serializer.validated_data,
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        """Apply the change and answer with the updated category.

        The update serializer declares only the fields a caller may change, so
        returning its data would echo the request and hide the result. The
        full representation keeps a client from reverting the screen to the
        values it sent.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(CategorySerializer(serializer.instance).data)

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if category.products.exists():
            return Response(
                {
                    "error": {
                        "code": "validation_error",
                        "message": "Cannot delete a category that has products.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        delete_category(category=category, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        summary="List products",
        description=(
            "Paginated list of products with current price. Supports filtering by "
            "``?category=`` (ID), ``?active=`` (true/false), ``?stock_tracked=`` (true/false), "
            "and search via ``?search=`` (matches name, SKU, description). "
            "Requires ``products.view_products`` (all staff roles)."
        ),
        tags=["products"],
    ),
    retrieve=extend_schema(
        summary="Get a product",
        description=(
            "Single product with full price history and current stock. "
            "Requires ``products.view_products``."
        ),
        tags=["products"],
    ),
    create=extend_schema(
        summary="Create a product",
        description=(
            "Create a new sellable product. Requires ``products.manage_products`` (Owner)."
        ),
        request=ProductCreateSerializer,
        responses={201: ProductSerializer},
        tags=["products"],
    ),
    partial_update=extend_schema(
        summary="Update a product",
        description="Partially update a product (name, unit, stock tracking, active, description). "
        "Requires ``products.manage_products``.",
        tags=["products"],
    ),
    destroy=extend_schema(
        summary="Retire a product",
        description=(
            "Mark a product inactive (cannot be sold but keeps history). "
            "Requires ``products.manage_products``."
        ),
        tags=["products"],
    ),
)
class ProductViewSet(viewsets.ModelViewSet):
    """CRUD for sellable products.

    List/retrieve: ``CanViewProducts`` (all staff roles).
    Write: ``CanManageProducts`` (Owner only).
    Price actions: ``CanChangePrices`` (Owner only).

    The two price actions answer on separate paths - ``prices`` to add one,
    ``prices/history`` to read them back - because a router turns each action into
    its own route and Django resolves by path alone, never by method. Two actions
    sharing ``url_path="prices"`` produce two identical routes, the second is
    unreachable, and the one that is reachable answers 405 for the other's method.
    """

    queryset = Product.objects.select_related("category").order_by(
        "category__display_order", "name"
    )
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_serializer_class(self):
        if self.action == "create":
            return ProductCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ProductUpdateSerializer
        if self.action == "list":
            return ProductListSerializer
        return ProductSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewProducts()]
        if self.action in {"set_price", "price_history"}:
            return [IsAuthenticated(), CanChangePrices()]
        return [IsAuthenticated(), CanManageProducts()]

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category_id=positive_int(category, "category"))
        active = self.request.query_params.get("active")
        if active is not None:
            qs = qs.filter(is_active=boolean_value(active, "active"))
        stock_tracked = self.request.query_params.get("stock_tracked")
        if stock_tracked is not None:
            qs = qs.filter(is_stock_tracked=boolean_value(stock_tracked, "stock_tracked"))
        search = self.request.query_params.get("search")
        if search:
            qs = (
                qs.filter(name__icontains=search)
                | qs.filter(sku__icontains=search)
                | qs.filter(description__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        serializer.instance = create_product(
            category=serializer.validated_data["category"],
            name=serializer.validated_data["name"],
            sku=serializer.validated_data["sku"],
            unit=serializer.validated_data.get("unit", "bottle"),
            quantity_mode=serializer.validated_data.get("quantity_mode", "WHOLE"),
            bottles_per_crate=serializer.validated_data.get("bottles_per_crate"),
            is_stock_tracked=serializer.validated_data.get("is_stock_tracked", True),
            description=serializer.validated_data.get("description", ""),
            actor=self.request.user,  # type: ignore[arg-type]
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        """Create a product and answer with its full representation.

        ``ProductCreateSerializer`` is a plain ``Serializer`` - it carries only
        the fields a caller sends, so it has no ``id``. The default create flow
        would therefore answer with the input echoed back, and a client that
        needs the new product's id to continue (setting its price is a second
        request keyed by that id) would have nothing to key on. Serializing the
        created instance with ``ProductSerializer`` returns that id, along with
        the current price and stock the list and edit screens read.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        output = ProductSerializer(serializer.instance).data
        headers = self.get_success_headers(output)
        return Response(output, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        serializer.instance = update_product(
            product=self.get_object(),
            actor=self.request.user,  # type: ignore[arg-type]
            **serializer.validated_data,
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        """Apply the change and answer with the full updated product."""
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(ProductSerializer(serializer.instance).data)

    def destroy(self, request, *args, **kwargs):
        """Retire (deactivate) instead of hard delete."""
        product = self.get_object()
        if not product.is_active:
            return Response(
                {
                    "error": {
                        "code": "validation_error",
                        "message": "Product is already retired.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        retire_product(product=product, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Set a new price for this product",
        description=(
            "Creates a new price row effective from ``effective_from`` (default: now). "
            "Previous prices remain in history. Requires ``products.change_prices``."
        ),
        request=ProductPriceCreateSerializer,
        responses={201: ProductPriceSerializer},
        tags=["products"],
    )
    @action(detail=True, methods=["post"], url_path="prices")
    def set_price(self, request: Request, pk: int | None = None) -> Response:
        """Add a new price for this product."""
        product = self.get_object()
        serializer = ProductPriceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        price = set_product_price(
            product=product,
            unit_price=serializer.validated_data["unit_price"],
            currency=serializer.validated_data["currency"],
            effective_from=serializer.validated_data.get("effective_from"),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(ProductPriceSerializer(price).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Get price history for this product",
        description=(
            "Returns all price rows for this product, newest first. "
            "Requires ``products.change_prices``."
        ),
        responses={200: ProductPriceSerializer(many=True)},
        tags=["products"],
    )
    @action(detail=True, methods=["get"], url_path="prices/history")
    def price_history(self, request: Request, pk: int | None = None) -> Response:
        """Return all price rows for this product."""
        product = self.get_object()
        prices = product.price_history.all()
        return Response(ProductPriceSerializer(prices, many=True).data)


__all__ = ["CategoryViewSet", "ProductViewSet"]
