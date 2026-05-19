// =============================================================================
// Aether SDK — E-COMMERCE MODULE (Android)
// Revenue tracking: product views, cart, checkout funnel, purchases
// =============================================================================

package com.aether.sdk

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

// =============================================================================
// TYPES
// =============================================================================

data class AetherProduct(
    val id: String,
    val name: String,
    val category: String? = null,
    val brand: String? = null,
    val variant: String? = null,
    val price: Double = 0.0,
    val quantity: Int? = null,
    val currency: String? = null,
    val coupon: String? = null
) {
    fun toMap(): Map<String, Any?> {
        val map = mutableMapOf<String, Any?>(
            "product_id" to id,
            "name" to name,
            "price" to price
        )
        category?.let { map["category"] = it }
        brand?.let { map["brand"] = it }
        variant?.let { map["variant"] = it }
        quantity?.let { map["quantity"] = it }
        currency?.let { map["currency"] = it }
        coupon?.let { map["coupon"] = it }
        return map
    }

    fun toJSONObject(): JSONObject = JSONObject(toMap().filterValues { it != null })
}

data class AetherCartItem(
    val product: AetherProduct,
    val quantity: Int
) {
    fun toMap(): Map<String, Any?> {
        val map = product.toMap().toMutableMap()
        map["quantity"] = quantity
        return map
    }

    fun toJSONObject(): JSONObject = JSONObject(toMap().filterValues { it != null })
}

data class AetherOrder(
    val orderId: String,
    val revenue: Double,
    val tax: Double? = null,
    val shipping: Double? = null,
    val discount: Double? = null,
    val coupon: String? = null,
    val currency: String? = null,
    val products: List<AetherProduct> = emptyList()
) {
    fun toMap(): Map<String, Any?> {
        val map = mutableMapOf<String, Any?>(
            "order_id" to orderId,
            "revenue" to revenue
        )
        tax?.let { map["tax"] = it }
        shipping?.let { map["shipping"] = it }
        discount?.let { map["discount"] = it }
        coupon?.let { map["coupon"] = it }
        currency?.let { map["currency"] = it }
        if (products.isNotEmpty()) {
            map["products"] = products.map { it.toMap() }
        }
        return map
    }

    fun toJSONObject(): JSONObject = JSONObject(toMap().filterValues { it != null })
}

// =============================================================================
// ECOMMERCE MODULE
// =============================================================================

object AetherEcommerce {
    private const val PREFS_NAME = "com.aether.sdk.ecommerce"
    private const val CART_KEY = "aether_cart"

    private var prefs: SharedPreferences? = null

    /** In-memory cart keyed by product ID. Thread-safe. */
    private val cart = ConcurrentHashMap<String, AetherCartItem>()

    /**
     * Initialize the ecommerce module. Call once from Application.onCreate().
     */
    fun initialize(context: Context) {
        prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        loadCart()
    }

    // =========================================================================
    // PRODUCT EVENTS
    // =========================================================================

    /** Track when a user views a product. */
    fun productViewed(product: AetherProduct) {
        Aether.track("product_viewed", product.toMap())
    }

    /** Track when a user views a product list / collection. */
    fun productListViewed(listId: String, products: List<AetherProduct>) {
        val props = mutableMapOf<String, Any?>(
            "list_id" to listId,
            "products" to products.map { it.toMap() },
            "product_count" to products.size
        )
        Aether.track("product_list_viewed", props)
    }

    // =========================================================================
    // CART MANAGEMENT
    // =========================================================================

    /** Add a product to the cart (or update quantity if already present). */
    fun addToCart(product: AetherProduct, quantity: Int = 1) {
        synchronized(cart) {
            val existing = cart[product.id]
            if (existing != null) {
                cart[product.id] = AetherCartItem(product, existing.quantity + quantity)
            } else {
                cart[product.id] = AetherCartItem(product, maxOf(1, quantity))
            }
            persistCart()
        }

        val props = product.toMap().toMutableMap()
        props["quantity"] = quantity
        Aether.track("add_to_cart", props)
    }

    /** Remove a product from the cart by its ID. */
    fun removeFromCart(productId: String) {
        val removedProps: Map<String, Any?>
        synchronized(cart) {
            val item = cart.remove(productId)
            removedProps = item?.toMap() ?: mapOf("product_id" to productId)
            persistCart()
        }
        Aether.track("remove_from_cart", removedProps)
    }

    /** Track a cart-viewed event with all current items. */
    fun cartViewed() {
        Aether.track("cart_viewed", cartSnapshot())
    }

    /** Get all items currently in the cart. */
    fun getCart(): List<AetherCartItem> {
        return synchronized(cart) { cart.values.toList() }
    }

    /** Calculate total cart value (price * quantity for each item). */
    fun getCartValue(): Double {
        return synchronized(cart) {
            cart.values.sumOf { it.product.price * it.quantity }
        }
    }

    /** Remove all items from the cart. */
    fun clearCart() {
        synchronized(cart) {
            cart.clear()
            persistCart()
        }
    }

    // =========================================================================
    // CHECKOUT FUNNEL
    // =========================================================================

    /** Track the start of a checkout. */
    fun checkoutStarted(properties: Map<String, Any?> = emptyMap()) {
        val props = cartSnapshot().toMutableMap()
        props.putAll(properties)
        Aether.track("checkout_started", props)
    }

    /** Track individual checkout steps (e.g., shipping, payment, review). */
    fun checkoutStepCompleted(step: Int, properties: Map<String, Any?> = emptyMap()) {
        val props = mutableMapOf<String, Any?>("step" to step)
        props.putAll(properties)
        Aether.track("checkout_step_completed", props)
    }

    // =========================================================================
    // ORDER EVENTS
    // =========================================================================

    /** Track a completed purchase. */
    fun orderCompleted(order: AetherOrder) {
        Aether.track("order_completed", order.toMap())
        clearCart()
    }

    /** Track a full or partial refund. */
    fun orderRefunded(orderId: String, products: List<AetherProduct>? = null) {
        val props = mutableMapOf<String, Any?>("order_id" to orderId)
        if (!products.isNullOrEmpty()) {
            props["products"] = products.map { it.toMap() }
            props["full_refund"] = false
        } else {
            props["full_refund"] = true
        }
        Aether.track("order_refunded", props)
    }

    // =========================================================================
    // COUPONS
    // =========================================================================

    /** Track when a coupon is applied. */
    fun couponApplied(coupon: String, discount: Double? = null) {
        val props = mutableMapOf<String, Any?>("coupon" to coupon)
        discount?.let { props["discount"] = it }
        Aether.track("coupon_applied", props)
    }

    // =========================================================================
    // PERSISTENCE
    // =========================================================================

    private fun cartSnapshot(): Map<String, Any?> {
        return synchronized(cart) {
            mapOf(
                "products" to cart.values.map { it.toMap() },
                "cart_value" to cart.values.sumOf { it.product.price * it.quantity },
                "item_count" to cart.size
            )
        }
    }

    private fun persistCart() {
        val array = JSONArray()
        for (item in cart.values) {
            val obj = JSONObject().apply {
                put("product", item.product.toJSONObject())
                put("quantity", item.quantity)
            }
            array.put(obj)
        }
        prefs?.edit()?.putString(CART_KEY, array.toString())?.apply()
    }

    private fun loadCart() {
        val raw = prefs?.getString(CART_KEY, null) ?: return
        try {
            val array = JSONArray(raw)
            for (i in 0 until array.length()) {
                val obj = array.getJSONObject(i)
                val pObj = obj.getJSONObject("product")
                val product = AetherProduct(
                    id = pObj.getString("product_id"),
                    name = pObj.getString("name"),
                    category = pObj.optString("category", null),
                    brand = pObj.optString("brand", null),
                    variant = pObj.optString("variant", null),
                    price = pObj.optDouble("price", 0.0),
                    quantity = if (pObj.has("quantity")) pObj.getInt("quantity") else null,
                    currency = pObj.optString("currency", null),
                    coupon = pObj.optString("coupon", null)
                )
                val qty = obj.getInt("quantity")
                cart[product.id] = AetherCartItem(product, qty)
            }
        } catch (_: Exception) {
            // Corrupted cache — start fresh
            cart.clear()
        }
    }
}
