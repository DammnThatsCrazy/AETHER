// =============================================================================
// Aether SDK — E-COMMERCE MODULE (iOS)
// Revenue tracking: product views, cart, checkout funnel, purchases
// =============================================================================

import Foundation

// MARK: - Types

public struct AetherProduct: Codable {
    public let id: String
    public let name: String
    public var category: String?
    public var brand: String?
    public var variant: String?
    public var price: Double
    public var quantity: Int?
    public var currency: String?
    public var coupon: String?

    public init(
        id: String,
        name: String,
        category: String? = nil,
        brand: String? = nil,
        variant: String? = nil,
        price: Double = 0,
        quantity: Int? = nil,
        currency: String? = nil,
        coupon: String? = nil
    ) {
        self.id = id
        self.name = name
        self.category = category
        self.brand = brand
        self.variant = variant
        self.price = price
        self.quantity = quantity
        self.currency = currency
        self.coupon = coupon
    }

    func toProperties() -> [String: AnyCodable] {
        var props: [String: AnyCodable] = [
            "product_id": AnyCodable(id),
            "name": AnyCodable(name),
            "price": AnyCodable(price)
        ]
        if let category = category { props["category"] = AnyCodable(category) }
        if let brand = brand { props["brand"] = AnyCodable(brand) }
        if let variant = variant { props["variant"] = AnyCodable(variant) }
        if let quantity = quantity { props["quantity"] = AnyCodable(quantity) }
        if let currency = currency { props["currency"] = AnyCodable(currency) }
        if let coupon = coupon { props["coupon"] = AnyCodable(coupon) }
        return props
    }
}

public struct AetherCartItem: Codable {
    public let product: AetherProduct
    public let quantity: Int

    public init(product: AetherProduct, quantity: Int) {
        self.product = product
        self.quantity = max(1, quantity)
    }

    func toProperties() -> [String: AnyCodable] {
        var props = product.toProperties()
        props["quantity"] = AnyCodable(quantity)
        return props
    }
}

public struct AetherOrder: Codable {
    public let orderId: String
    public let revenue: Double
    public var tax: Double?
    public var shipping: Double?
    public var discount: Double?
    public var coupon: String?
    public var currency: String?
    public var products: [AetherProduct]

    public init(
        orderId: String,
        revenue: Double,
        tax: Double? = nil,
        shipping: Double? = nil,
        discount: Double? = nil,
        coupon: String? = nil,
        currency: String? = nil,
        products: [AetherProduct] = []
    ) {
        self.orderId = orderId
        self.revenue = revenue
        self.tax = tax
        self.shipping = shipping
        self.discount = discount
        self.coupon = coupon
        self.currency = currency
        self.products = products
    }

    func toProperties() -> [String: AnyCodable] {
        var props: [String: AnyCodable] = [
            "order_id": AnyCodable(orderId),
            "revenue": AnyCodable(revenue)
        ]
        if let tax = tax { props["tax"] = AnyCodable(tax) }
        if let shipping = shipping { props["shipping"] = AnyCodable(shipping) }
        if let discount = discount { props["discount"] = AnyCodable(discount) }
        if let coupon = coupon { props["coupon"] = AnyCodable(coupon) }
        if let currency = currency { props["currency"] = AnyCodable(currency) }
        if !products.isEmpty {
            props["products"] = AnyCodable(products.map { $0.toProperties().mapValues { $0.value } })
        }
        return props
    }
}

// MARK: - AetherEcommerce

public final class AetherEcommerce {
    public static let shared = AetherEcommerce()

    private let serialQueue = DispatchQueue(label: "com.aether.sdk.ecommerce")
    private let defaults = UserDefaults(suiteName: "com.aether.sdk")!
    private let cartKey = "aether_cart"

    /// In-memory cart keyed by product ID.
    private var cart: [String: AetherCartItem] = [:]

    private init() {
        loadCart()
    }

    // MARK: - Product Events

    /// Track when a user views a product.
    public func productViewed(_ product: AetherProduct) {
        Aether.shared.track("product_viewed", properties: product.toProperties())
    }

    /// Track when a user views a product list / collection.
    public func productListViewed(listId: String, products: [AetherProduct]) {
        var props: [String: AnyCodable] = [
            "list_id": AnyCodable(listId),
            "products": AnyCodable(products.map { $0.toProperties().mapValues { $0.value } })
        ]
        props["product_count"] = AnyCodable(products.count)
        Aether.shared.track("product_list_viewed", properties: props)
    }

    // MARK: - Cart Management

    /// Add a product to the cart (or update quantity if already present).
    public func addToCart(_ product: AetherProduct, quantity: Int = 1) {
        serialQueue.async { [weak self] in
            guard let self = self else { return }
            let item = AetherCartItem(product: product, quantity: quantity)
            if let existing = self.cart[product.id] {
                let merged = AetherCartItem(
                    product: product,
                    quantity: existing.quantity + quantity
                )
                self.cart[product.id] = merged
            } else {
                self.cart[product.id] = item
            }
            self.persistCart()
        }

        var props = product.toProperties()
        props["quantity"] = AnyCodable(quantity)
        Aether.shared.track("add_to_cart", properties: props)
    }

    /// Remove a product from the cart by its ID.
    public func removeFromCart(productId: String) {
        var removedProps: [String: AnyCodable] = ["product_id": AnyCodable(productId)]
        serialQueue.sync {
            if let item = cart[productId] {
                removedProps = item.toProperties()
                cart.removeValue(forKey: productId)
                persistCart()
            }
        }
        Aether.shared.track("remove_from_cart", properties: removedProps)
    }

    /// Track a cart-viewed event with all current items.
    public func cartViewed() {
        let snapshot = serialQueue.sync { cartSnapshot() }
        Aether.shared.track("cart_viewed", properties: snapshot)
    }

    /// Get all items currently in the cart.
    public func getCart() -> [AetherCartItem] {
        return serialQueue.sync { Array(cart.values) }
    }

    /// Calculate total cart value (price * quantity for each item).
    public func getCartValue() -> Double {
        return serialQueue.sync {
            cart.values.reduce(0.0) { $0 + ($1.product.price * Double($1.quantity)) }
        }
    }

    /// Remove all items from the cart.
    public func clearCart() {
        serialQueue.async { [weak self] in
            self?.cart.removeAll()
            self?.persistCart()
        }
    }

    // MARK: - Checkout Funnel

    /// Track the start of a checkout.
    public func checkoutStarted(properties: [String: AnyCodable]? = nil) {
        var props = serialQueue.sync { cartSnapshot() }
        if let extra = properties {
            props.merge(extra) { _, new in new }
        }
        Aether.shared.track("checkout_started", properties: props)
    }

    /// Track individual checkout steps (e.g., shipping, payment, review).
    public func checkoutStepCompleted(step: Int, properties: [String: AnyCodable]? = nil) {
        var props: [String: AnyCodable] = ["step": AnyCodable(step)]
        if let extra = properties {
            props.merge(extra) { _, new in new }
        }
        Aether.shared.track("checkout_step_completed", properties: props)
    }

    // MARK: - Order Events

    /// Track a completed purchase.
    public func orderCompleted(_ order: AetherOrder) {
        Aether.shared.track("order_completed", properties: order.toProperties())

        // Clear cart after successful order
        clearCart()
    }

    /// Track a full or partial refund.
    public func orderRefunded(orderId: String, products: [AetherProduct]? = nil) {
        var props: [String: AnyCodable] = ["order_id": AnyCodable(orderId)]
        if let products = products, !products.isEmpty {
            props["products"] = AnyCodable(products.map { $0.toProperties().mapValues { $0.value } })
            props["full_refund"] = AnyCodable(false)
        } else {
            props["full_refund"] = AnyCodable(true)
        }
        Aether.shared.track("order_refunded", properties: props)
    }

    // MARK: - Coupons

    /// Track when a coupon is applied.
    public func couponApplied(coupon: String, discount: Double? = nil) {
        var props: [String: AnyCodable] = ["coupon": AnyCodable(coupon)]
        if let discount = discount {
            props["discount"] = AnyCodable(discount)
        }
        Aether.shared.track("coupon_applied", properties: props)
    }

    // MARK: - Persistence

    private func cartSnapshot() -> [String: AnyCodable] {
        let items = cart.values.map { $0.toProperties().mapValues { $0.value } }
        return [
            "products": AnyCodable(items),
            "cart_value": AnyCodable(cart.values.reduce(0.0) { $0 + ($1.product.price * Double($1.quantity)) }),
            "item_count": AnyCodable(cart.count)
        ]
    }

    private func persistCart() {
        guard let data = try? JSONEncoder().encode(Array(cart.values)) else { return }
        defaults.set(data, forKey: cartKey)
    }

    private func loadCart() {
        guard let data = defaults.data(forKey: cartKey),
              let items = try? JSONDecoder().decode([AetherCartItem].self, from: data) else { return }
        for item in items {
            cart[item.product.id] = item
        }
    }
}
