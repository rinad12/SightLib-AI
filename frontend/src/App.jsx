import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BookOpen,
  Camera,
  Search,
  Sparkles,
  Plus,
  X,
  Compass,
  Loader2,
  User,
  Info,
  BookMarked
} from 'lucide-react';

const API_BASE = '/api'; // Proxied to the backend by Vite (see vite.config.js) so cookies stay same-origin
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;

// Fixed genre list - keep in sync with GENRES in app/agent.py
const GENRES = [
  'Fiction', 'Fantasy', 'Sci-Fi', 'Mystery & Thriller', 'Romance', 'Horror',
  'Historical Fiction', 'Young Adult', "Children's", 'Biography & Memoir',
  'History', 'Science', 'Self-Help', 'Business', 'Poetry', 'Other',
];

// Color palette for the skeuomorphic book spines - warm, muted tones to match the cozy theme
const SPINE_COLORS = [
  'bg-gradient-to-r from-rose-700 to-rose-900 border-rose-600',
  'bg-gradient-to-r from-sky-700 to-sky-900 border-sky-600',
  'bg-gradient-to-r from-emerald-700 to-emerald-900 border-emerald-600',
  'bg-gradient-to-r from-amber-700 to-amber-900 border-amber-600',
  'bg-gradient-to-r from-orange-700 to-orange-900 border-orange-600',
  'bg-gradient-to-r from-fuchsia-700 to-fuchsia-900 border-fuchsia-600',
  'bg-gradient-to-r from-red-700 to-red-900 border-red-600',
  'bg-gradient-to-r from-teal-700 to-teal-900 border-teal-600',
  'bg-gradient-to-r from-stone-600 to-stone-800 border-stone-500',
];

export default function App() {
  const [library, setLibrary] = useState([]);
  const [loading, setLoading] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  const [runningAction, setRunningAction] = useState(null); // 'scan' | 'search' | 'recommend' - which button shows the spinner
  
  // Modals and Forms
  const [selectedBook, setSelectedBook] = useState(null);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editForm, setEditForm] = useState({ title: '', author: '', genre: '', description: '', status: 'unread' });
  const [isManualEntry, setIsManualEntry] = useState(false);
  const [editingBookId, setEditingBookId] = useState(null); // set when editing an existing shelf book instead of adding a new one
  const [editingScannedIndex, setEditingScannedIndex] = useState(null); // set when the edit form was opened from a scannedBooks entry
  
  // Search & Recommendations
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [recommendedBookIds, setRecommendedBookIds] = useState([]);
  const [recommendedBooksInfo, setRecommendedBooksInfo] = useState([]); // {title, author} for the "How about..." callout
  const [quotaStatus, setQuotaStatus] = useState(null);
  const [quotaAction, setQuotaAction] = useState(null); // e.g. 'add-manually' to show a shortcut button next to the message

  // Books detected in a single scanned photo (stack/shelf), pending individual review
  const [scannedBooks, setScannedBooks] = useState([]);
  
  // Scanning state
  const [scanningImage, setScanningImage] = useState(null);
  const fileInputRef = useRef(null);

  // Google Sign-In state
  const [authChecked, setAuthChecked] = useState(false);
  const [userEmail, setUserEmail] = useState(null);
  const [demoMode, setDemoMode] = useState(false); // server-controlled: shows a no-login "guest" button for demo recordings
  const googleButtonRef = useRef(null);

  // Check for an existing session on mount; only load the library once authenticated
  useEffect(() => {
    checkAuth();
    fetch(`${API_BASE}/config`)
      .then((res) => res.json())
      .then((data) => setDemoMode(!!data.demo_mode))
      .catch((err) => console.error('Failed to load config:', err));
  }, []);

  const checkAuth = async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/me`, { credentials: 'include' });
      const data = await res.json();
      if (data.authenticated) {
        setUserEmail(data.email);
      }
    } catch (err) {
      console.error('Failed to check auth session:', err);
    } finally {
      setAuthChecked(true);
    }
  };

  useEffect(() => {
    if (userEmail) {
      fetchLibrary();
    }
  }, [userEmail]);

  // Render the Google Sign-In button once the script has loaded and we know we're logged out
  useEffect(() => {
    if (authChecked && !userEmail && !demoMode && window.google && googleButtonRef.current) {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleCredential,
        // FedCM can misbehave on non-HTTPS local dev origins; fall back to the classic prompt/button flow.
        use_fedcm_for_prompt: false,
      });
      window.google.accounts.id.renderButton(googleButtonRef.current, {
        theme: 'filled_black',
        size: 'large',
        shape: 'pill',
      });
    }
  }, [authChecked, userEmail, demoMode]);

  const handleGuestLogin = async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/guest`, { method: 'POST', credentials: 'include' });
      const data = await res.json();
      if (data.status === 'success') {
        setUserEmail(data.email);
      }
    } catch (err) {
      console.error('Guest sign-in failed:', err);
    }
  };

  const handleGoogleCredential = async (response) => {
    try {
      const res = await fetch(`${API_BASE}/auth/google`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id_token: response.credential }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setUserEmail(data.email);
      }
    } catch (err) {
      console.error('Google sign-in failed:', err);
    }
  };

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'include' });
    } catch (err) {
      console.error('Logout failed:', err);
    } finally {
      setUserEmail(null);
      setLibrary([]);
    }
  };

  const fetchLibrary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/library`, { credentials: 'include' });
      const data = await res.json();
      if (data.status === 'success') {
        setLibrary(data.items || []);
      }
    } catch (err) {
      console.error('Failed to fetch library:', err);
    } finally {
      setLoading(false);
    }
  };

  // 1. Photo Upload / OCR Pipeline
  const handlePhotoUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async () => {
      const base64 = reader.result.split(',')[1];
      setScanningImage(reader.result);
      setAgentRunning(true);
      setRunningAction('scan');
      setSearchResults([]); // Clear search to focus on scan
      setScannedBooks([]);
      setRecommendedBookIds([]); // Clear recommendations
      setRecommendedBooksInfo([]);
      setQuotaStatus(null);
      setQuotaAction(null);

      try {
        const response = await fetch(`${API_BASE}/process-book-photo`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_bytes: base64
          })
        });
        const data = await response.json();

        if (data.status === 'quota_exceeded') {
          // Check this FIRST - quota_exceeded responses also have an empty items array,
          // so a looser check further down would (and used to) swallow this case.
          setQuotaStatus('Daily photo scan limit reached (max 3/day). Try again tomorrow, or add this book manually.');
          setQuotaAction('add-manually');
        } else if (data.status === 'success' && data.items && data.items.length === 1) {
          // Exactly one book found - go straight to reviewing it, like before.
          const draft = data.items[0];
          setEditForm({
            title: draft.title || '',
            author: draft.author || '',
            genre: draft.genre || '',
            description: draft.description || '',
            status: 'unread'
          });
          setIsManualEntry(false);
          setEditingBookId(null);
          setEditingScannedIndex(null);
          setShowEditModal(true);
        } else if (data.status === 'success' && data.items && data.items.length > 1) {
          // Multiple books found in the photo (stack/shelf) - let the user review each one.
          setScannedBooks(data.items);
        } else if (data.status === 'manual_input_required' || !data.items || data.items.length === 0) {
          // Fallback to manual entry if OCR failed to find any book
          setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
          setIsManualEntry(true);
          setEditingBookId(null);
          setEditingScannedIndex(null);
          setShowEditModal(true);
        }
      } catch (err) {
        console.error('OCR pipeline failed:', err);
        // Fallback to manual form
        setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
        setIsManualEntry(true);
        setEditingBookId(null);
        setEditingScannedIndex(null);
        setShowEditModal(true);
      } finally {
        setAgentRunning(false);
        setRunningAction(null);
        setScanningImage(null);
      }
    };
    reader.readAsDataURL(file);
  };

  // 2. Direct DB Save (confirm save from form) - creates a new book, or edits an existing one if editingBookId is set
  const handleSaveBook = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const url = editingBookId ? `${API_BASE}/books/${editingBookId}` : `${API_BASE}/books`;
      const method = editingBookId ? 'PUT' : 'POST';
      const res = await fetch(url, {
        method,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm)
      });
      const data = await res.json();
      if (data.status === 'success') {
        setShowEditModal(false);
        setEditingBookId(null);
        if (editingScannedIndex !== null) {
          setScannedBooks(prev => prev.filter((_, i) => i !== editingScannedIndex));
          setEditingScannedIndex(null);
        }
        fetchLibrary();
      }
    } catch (err) {
      console.error('Failed to save book:', err);
    } finally {
      setLoading(false);
    }
  };

  // Delete a book from the shelf (plain REST call - no LLM/agent involvement)
  const handleDeleteBook = async () => {
    if (!selectedBook) return;
    if (!window.confirm(`Remove "${selectedBook.title}" from your shelf? This can't be undone.`)) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/books/${selectedBook.id}`, {
        method: 'DELETE',
        credentials: 'include',
      });
      const data = await res.json();
      if (data.status === 'success') {
        setSelectedBook(null);
        fetchLibrary();
      }
    } catch (err) {
      console.error('Failed to delete book:', err);
    } finally {
      setLoading(false);
    }
  };

  // Update book status from details modal
  const handleUpdateStatus = async (status) => {
    if (!selectedBook) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/books`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: selectedBook.title,
          author: selectedBook.author,
          genre: selectedBook.genre,
          description: selectedBook.description,
          status: status
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        setSelectedBook(prev => ({ ...prev, status }));
        fetchLibrary();
      }
    } catch (err) {
      console.error('Failed to update status:', err);
    } finally {
      setLoading(false);
    }
  };

  // 3. Contextual Search
  const handleSearch = async (e, forceSurprise = false) => {
    if (e) e.preventDefault();
    const query = forceSurprise ? '' : searchQuery;
    if (!query && !forceSurprise && library.length === 0) {
      // Both empty
      setSearchResults([]);
      setQuotaStatus('Please enter a search term or add books to your library first.');
      setQuotaAction(null);
      return;
    }

    setAgentRunning(true);
    setRunningAction('search');
    setSearchResults([]);
    setRecommendedBookIds([]);
    setRecommendedBooksInfo([]);
    setScannedBooks([]);
    setQuotaStatus(null);
    setQuotaAction(null);

    try {
      const response = await fetch(`${API_BASE}/search-books`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query || null })
      });
      const data = await response.json();

      if (data.status === 'success' && data.items) {
        setSearchResults(data.items);
        if (data.items.length === 0) {
          setQuotaStatus('No books found. Try a different word or phrase.');
        }
      } else if (data.status === 'missing_context') {
        setQuotaStatus('No context. Enter a search term or add books to your shelf first.');
      } else if (data.status === 'quota_exceeded') {
        setQuotaStatus('Search quota exceeded (Max 5 searches/day).');
      } else {
        // Covers status === 'error' and any other unexpected response - never fail silently.
        console.error('Search failed:', data);
        setQuotaStatus(data.message || 'Something went wrong while searching. Please try again.');
      }
    } catch (err) {
      console.error('Search failed:', err);
      setQuotaStatus('Something went wrong while searching. Please try again.');
    } finally {
      setAgentRunning(false);
      setRunningAction(null);
    }
  };

  // 4. Personalized Recommendations (highlight existing shelf)
  const handleGetRecommendations = async () => {
    setAgentRunning(true);
    setRunningAction('recommend');
    setRecommendedBookIds([]);
    setRecommendedBooksInfo([]);
    setSearchResults([]);
    setScannedBooks([]);
    setQuotaStatus(null);
    setQuotaAction(null);

    try {
      const response = await fetch(`${API_BASE}/recommend-books`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preference: searchQuery || null })
      });
      const data = await response.json();

      if (data.status === 'success' && data.items) {
        // Shelf-only recommendation: map picked titles back to shelf book IDs to highlight,
        // and keep title/author around so we can name them explicitly in a callout too -
        // the glow on the shelf alone is too easy to miss.
        const matched = data.items
          .map(rec => library.find(lib => lib.title.toLowerCase() === (rec.title || '').toLowerCase()))
          .filter(Boolean);
        const ids = matched.map(b => b.id);

        setRecommendedBookIds(ids);
        setRecommendedBooksInfo(matched.map(b => ({ id: b.id, title: b.title, author: b.author })));
        if (ids.length === 0) {
          setQuotaStatus(
            searchQuery
              ? `No book on your shelf matches "${searchQuery}". Try a different word, or use "Search Online" to find something new.`
              : 'No matching books found on your shelf.'
          );
        }
      } else if (data.status === 'empty_library') {
        setQuotaStatus('Add some books to your shelf first to get shelf recommendations.');
      } else if (data.status === 'quota_exceeded') {
        setQuotaStatus('Recommendations quota exceeded (Max 5/day).');
      } else {
        // Covers status === 'error' and any other unexpected response - never fail silently.
        console.error('Recommendations failed:', data);
        setQuotaStatus(data.message || 'Something went wrong while getting recommendations. Please try again.');
      }
    } catch (err) {
      console.error('Recommendations failed:', err);
      setQuotaStatus('Something went wrong while getting recommendations. Please try again.');
    } finally {
      setAgentRunning(false);
      setRunningAction(null);
    }
  };

  // Helper to split books onto shelves (6 books per shelf)
  const booksPerShelf = 6;
  const shelvesCount = Math.max(2, Math.ceil(library.length / booksPerShelf));
  const shelves = Array.from({ length: shelvesCount }, (_, index) => {
    return library.slice(index * booksPerShelf, (index + 1) * booksPerShelf);
  });

  if (!authChecked) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-amber-50 via-orange-50 to-amber-100 flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-amber-600 animate-spin" />
      </div>
    );
  }

  if (!userEmail) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-amber-50 via-orange-50 to-amber-100 text-stone-800 flex flex-col items-center justify-center gap-6 px-6 text-center">
        <div className="p-4 bg-white shadow-lg shadow-amber-900/5 border border-amber-200 rounded-3xl text-amber-700">
          <BookOpen className="w-10 h-10" />
        </div>
        <div>
          <h1 className="font-heading text-4xl font-semibold text-amber-900">
            SightLib AI
          </h1>
          <p className="text-sm text-amber-700/70 mt-1">your cozy little reading nook</p>
        </div>
        <p className="text-sm text-stone-500 max-w-sm leading-relaxed">
          {demoMode
            ? 'Try it out instantly - no account needed.'
            : 'Sign in with Google to see your shelf and use the AI-powered features.'}
        </p>
        {demoMode ? (
          <button
            onClick={handleGuestLogin}
            className="px-6 py-3 bg-amber-700 hover:bg-amber-800 text-white font-medium rounded-full shadow-md shadow-amber-900/20 transition-colors"
          >
            Try without signing in
          </button>
        ) : (
          <div ref={googleButtonRef}></div>
        )}
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-amber-50 via-orange-50 to-amber-100 text-stone-800 flex flex-col font-sans selection:bg-amber-300 selection:text-amber-950 pb-16">

      {/* Decorative top lights */}
      <div className="absolute top-0 left-1/4 w-96 h-32 bg-amber-300/20 rounded-full blur-3xl pointer-events-none"></div>
      <div className="absolute top-0 right-1/4 w-96 h-32 bg-rose-300/20 rounded-full blur-3xl pointer-events-none"></div>

      {/* Header */}
      <header className="max-w-7xl mx-auto w-full px-4 sm:px-6 pt-6 sm:pt-8 pb-4 flex flex-col md:flex-row justify-between items-center border-b border-amber-200 gap-4 relative z-10">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-white border border-amber-200 rounded-xl text-amber-700 shadow-md shadow-amber-900/5">
            <BookOpen className="w-7 h-7 sm:w-8 sm:h-8" />
          </div>
          <div>
            <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-amber-900">
              SightLib AI
            </h1>
            <p className="text-xs text-amber-700/70">your cozy little reading nook</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-stone-500 order-last md:order-none">
          <User className="w-4 h-4 text-amber-600" />
          <span className="truncate max-w-[160px] sm:max-w-none">{userEmail}</span>
          <button
            onClick={handleLogout}
            className="ml-2 min-h-[36px] px-3 py-1.5 bg-white hover:bg-amber-50 border border-amber-200 rounded-lg text-stone-600 cursor-pointer transition duration-200"
          >
            Sign out
          </button>
        </div>

        {/* Add to Shelf - the only two actions in the header, both add a book */}
        <div className="flex flex-col gap-1.5 w-full md:w-auto">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-700/60 px-0.5">Add a book</span>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handlePhotoUpload}
              accept="image/*"
              className="hidden"
              id="book-cover-upload"
              name="book-cover-upload"
              aria-label="Upload book cover image"
            />

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={agentRunning || loading}
              className="flex-1 md:flex-none min-h-[44px] flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 text-white font-semibold rounded-xl transition duration-200 active:scale-95 shadow-lg shadow-amber-900/15 cursor-pointer"
            >
              {agentRunning && scanningImage ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Camera className="w-5 h-5" />
              )}
              Scan Cover
            </button>

            <button
              onClick={() => {
                setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
                setIsManualEntry(true);
                setEditingBookId(null);
                setEditingScannedIndex(null);
                setShowEditModal(true);
              }}
              className="flex-1 md:flex-none min-h-[44px] flex items-center justify-center gap-2 px-4 py-2.5 bg-white hover:bg-amber-50 text-stone-700 border border-amber-200 font-semibold rounded-xl transition duration-200 active:scale-95 cursor-pointer"
            >
              <Plus className="w-5 h-5" />
              Add Manually
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto w-full px-6 mt-8 flex flex-col lg:flex-row gap-8 relative z-10">
        
        {/* Left Side: Bookshelf Area (Skeuomorphic) */}
        <div className="flex-1 flex flex-col gap-12">
          
          {quotaStatus && (
            <div className="p-4 bg-rose-50 border border-rose-200 text-rose-700 rounded-xl flex flex-wrap items-center gap-3">
              <Info className="w-5 h-5 flex-shrink-0" />
              <p className="text-sm font-medium flex-1 min-w-[200px]">{quotaStatus}</p>
              {quotaAction === 'add-manually' && (
                <button
                  type="button"
                  onClick={() => {
                    setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
                    setIsManualEntry(true);
                    setEditingBookId(null);
                    setEditingScannedIndex(null);
                    setShowEditModal(true);
                    setQuotaStatus(null);
                    setQuotaAction(null);
                  }}
                  className="min-h-[36px] px-3 py-1.5 bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold rounded-lg transition duration-200 cursor-pointer flex-shrink-0"
                >
                  Add Manually
                </button>
              )}
            </div>
          )}

          {/* Shelves Container */}
          <div className="bg-white/70 border border-amber-200/70 p-4 sm:p-8 rounded-3xl shadow-xl shadow-amber-900/5 backdrop-blur-md">

            {library.length === 0 ? (
              <div className="py-16 sm:py-20 text-center flex flex-col items-center justify-center">
                <BookOpen className="w-16 h-16 text-amber-300 stroke-[1.5] mb-4" />
                <h3 className="font-heading text-xl text-amber-800">Your Bookshelf is Empty</h3>
                <p className="text-sm text-stone-500 mt-2 max-w-sm">
                  Click <b className="text-stone-700">Scan Cover</b> to upload a photo of a book, or <b className="text-stone-700">Add Manually</b> to place your first book spine here.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-12">
                {shelves.map((shelfBooks, sIdx) => (
                  <div key={sIdx} className="relative flex flex-col bookshelf-perspective">

                    {/* Books on the shelf */}
                    <div className="h-44 flex items-end px-4 sm:px-8 gap-3 sm:gap-4 justify-start overflow-x-auto overflow-y-visible z-10">
                      {shelfBooks.map((book) => {
                        const isRecommended = recommendedBookIds.includes(book.id);
                        const spineColor = SPINE_COLORS[Math.abs(book.title.charCodeAt(0) + book.title.charCodeAt(1 || 0)) % SPINE_COLORS.length];

                        return (
                          <motion.div
                            key={book.id}
                            onClick={() => setSelectedBook(book)}
                            className="relative cursor-pointer group overflow-visible flex-shrink-0"
                            style={{ transformOrigin: 'bottom center' }}
                            whileHover={{ y: -15, scale: 1.03 }}
                          >
                            {/* Glow if recommended */}
                            {isRecommended && (
                              <div className="absolute -inset-2 bg-rose-400/40 blur-lg rounded-md animate-pulse"></div>
                            )}

                            {/* Book Spine */}
                            <div className={`w-12 h-36 ${spineColor} rounded-t-sm shadow-md border-l-2 border-t border-r border-black/20 flex flex-col items-center justify-between py-4 select-none relative transition duration-300 group-hover:shadow-2xl`}>

                              {/* Status indicator on top of spine */}
                              <div className="w-1.5 h-1.5 rounded-full flex-shrink-0">
                                {book.status === 'read' && <div className="w-full h-full bg-emerald-400 rounded-full"></div>}
                                {book.status === 'reading' && <div className="w-full h-full bg-amber-300 rounded-full"></div>}
                                {book.status === 'unread' && <div className="w-full h-full bg-stone-300 rounded-full"></div>}
                              </div>

                              {/* Title (vertical) */}
                              <p className="text-[10px] font-bold tracking-wider text-amber-50/90 whitespace-nowrap overflow-hidden text-ellipsis uppercase max-w-[100px]" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
                                {book.title}
                              </p>

                              {/* Decorative stripes at the bottom */}
                              <div className="flex flex-col gap-1 w-full px-2 opacity-50">
                                <div className="h-0.5 bg-amber-50"></div>
                                <div className="h-0.5 bg-amber-50"></div>
                              </div>
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>

                    {/* Physical Shelf (Skeuomorphic wooden bar) */}
                    <div className="h-4 wooden-shelf w-full rounded-md z-0 shadow-lg relative">
                      {/* Shelf shadow underneath */}
                      <div className="absolute -bottom-4 left-0 right-0 h-4 bg-gradient-to-b from-amber-950/25 to-transparent"></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Search / Discovery / Side Panel */}
        <div className="w-full lg:w-96 flex flex-col gap-6">
          
          {/* Discovery / Search Bar - one input, two clearly labeled destinations */}
          <div className="bg-white/70 border border-amber-200/70 p-6 rounded-3xl shadow-xl shadow-amber-900/5 backdrop-blur-md">
            <h3 className="font-heading text-lg text-amber-800 mb-1 flex items-center gap-2">
              <Compass className="w-5 h-5" />
              What are you in the mood for?
            </h3>
            <p className="text-xs text-stone-500 mb-4">Type a vibe, genre, or leave it blank - then pick where to look.</p>

            <form onSubmit={handleSearch}>
              <div className="relative">
                <input
                  type="text"
                  placeholder="e.g. Cyberpunk 1980s..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full min-h-[44px] bg-amber-50/70 border border-amber-200 rounded-xl py-2 px-3 pl-9 text-base sm:text-sm text-stone-800 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400 transition duration-200"
                  id="book-search-input"
                  name="book-search"
                  aria-label="Search or discover books"
                />
                <Search className="w-4 h-4 text-amber-500 absolute left-3 top-1/2 -translate-y-1/2" />
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="submit"
                  disabled={agentRunning}
                  className="min-h-[44px] flex items-center justify-center gap-1.5 bg-amber-600 hover:bg-amber-500 disabled:bg-amber-300 text-white text-sm font-semibold rounded-xl transition duration-200 cursor-pointer"
                >
                  {runningAction === 'search' ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Searching...
                    </>
                  ) : (
                    <>
                      <Search className="w-4 h-4" />
                      Search Online
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={handleGetRecommendations}
                  disabled={agentRunning || library.length === 0}
                  title={library.length === 0 ? 'Add some books to your shelf first' : undefined}
                  className="min-h-[44px] flex items-center justify-center gap-1.5 bg-rose-100 hover:bg-rose-200 disabled:opacity-50 text-rose-700 text-sm font-semibold rounded-xl transition duration-200 cursor-pointer"
                >
                  {runningAction === 'recommend' ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Thinking...
                    </>
                  ) : (
                    <>
                      <BookMarked className="w-4 h-4" />
                      From My Shelf
                    </>
                  )}
                </button>
              </div>
            </form>

            <button
              onClick={() => handleSearch(null, true)}
              disabled={agentRunning}
              className="mt-2 w-full min-h-[44px] flex items-center justify-center gap-2 py-2 px-4 bg-white hover:bg-amber-50 border border-amber-200 rounded-xl text-xs font-semibold text-stone-600 transition duration-200 cursor-pointer"
            >
              {runningAction === 'search' ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 text-amber-600 animate-spin" />
                  Searching...
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-amber-600" />
                  Surprise Me (Discovery Mode)
                </>
              )}
            </button>
          </div>

          {/* Explicit callout naming the recommended book(s) - the glow on the shelf
              spine alone is too easy to miss, especially with several books on it. */}
          {recommendedBooksInfo.length > 0 && (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-3xl">
              <p className="text-sm font-semibold text-rose-800 flex items-center gap-2 mb-2">
                <Sparkles className="w-4 h-4" />
                {recommendedBooksInfo.length === 1 ? 'How about reading...' : 'How about one of these...'}
              </p>
              <div className="flex flex-col items-start gap-1">
                {recommendedBooksInfo.map((b) => (
                  <button
                    key={b.id}
                    type="button"
                    onClick={() => {
                      const book = library.find(lib => lib.id === b.id);
                      if (book) setSelectedBook(book);
                    }}
                    className="text-left text-sm text-rose-700 hover:text-rose-900 hover:underline cursor-pointer"
                  >
                    "{b.title}"{b.author && <span className="text-rose-500"> by {b.author}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Books detected in a scanned photo (stack/shelf) - review & add each one */}
          {scannedBooks.length > 0 && (
            <div className="bg-white/70 border border-amber-200/70 p-6 rounded-3xl shadow-xl shadow-amber-900/5 backdrop-blur-md">
              <h3 className="font-heading text-md text-amber-800 mb-1 flex items-center gap-2">
                <Camera className="w-4 h-4" />
                Found {scannedBooks.length} Books in Your Photo
              </h3>
              <p className="text-xs text-stone-500 mb-4">Click each one to review and add it to your shelf.</p>
              <div className="flex flex-col gap-3">
                {scannedBooks.map((book, idx) => (
                  <div
                    key={idx}
                    onClick={() => {
                      setEditForm({
                        title: book.title || '',
                        author: book.author || '',
                        genre: book.genre || '',
                        description: book.description || '',
                        status: 'unread'
                      });
                      setIsManualEntry(!book.title);
                      setEditingBookId(null);
                      setEditingScannedIndex(idx);
                      setShowEditModal(true);
                    }}
                    className="p-3 bg-amber-50/60 border border-amber-100 hover:border-amber-400 rounded-xl cursor-pointer transition duration-200 group flex items-start gap-3"
                  >
                    <BookMarked className="w-5 h-5 text-amber-400 group-hover:text-amber-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-semibold text-stone-800 group-hover:text-amber-700 line-clamp-1">
                        {book.title || 'Unreadable spine - tap to fill in manually'}
                      </h4>
                      {book.author && <p className="text-xs text-stone-500 mt-0.5">{book.author}</p>}
                      {book.genre && (
                        <span className="inline-block mt-1.5 px-2 py-0.5 bg-amber-100 text-[10px] text-amber-800 rounded-md">
                          {book.genre}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setScannedBooks(prev => prev.filter((_, i) => i !== idx));
                      }}
                      className="min-h-[32px] min-w-[32px] p-1.5 text-stone-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition duration-150 cursor-pointer flex-shrink-0"
                      aria-label={`Discard ${book.title || 'this book'}`}
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Discovery Shelf / Search Results */}
          {searchResults.length > 0 && (
            <div className="bg-white/70 border border-amber-200/70 p-6 rounded-3xl shadow-xl shadow-amber-900/5 backdrop-blur-md">
              <h3 className="font-heading text-md text-amber-800 mb-4">Books Found Online:</h3>
              <div className="flex flex-col gap-3">
                {searchResults.map((book, idx) => (
                  <div
                    key={idx}
                    onClick={() => {
                      setEditForm({
                        title: book.title || '',
                        author: book.author || '',
                        genre: book.genre || '',
                        description: book.description || '',
                        status: 'unread'
                      });
                      setIsManualEntry(false);
                      setEditingBookId(null);
                      setEditingScannedIndex(null);
                      setShowEditModal(true);
                    }}
                    className="p-3 bg-amber-50/60 border border-amber-100 hover:border-amber-400 rounded-xl cursor-pointer transition duration-200 group flex items-start gap-3"
                  >
                    <BookMarked className="w-5 h-5 text-amber-400 group-hover:text-amber-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-semibold text-stone-800 group-hover:text-amber-700 line-clamp-1">
                        {book.title}
                      </h4>
                      <p className="text-xs text-stone-500 mt-0.5">{book.author}</p>
                      {book.genre && (
                        <span className="inline-block mt-1.5 px-2 py-0.5 bg-amber-100 text-[10px] text-amber-800 rounded-md">
                          {book.genre}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Loading Scan Overlay */}
      {agentRunning && scanningImage && (
        <div className="fixed inset-0 bg-amber-950/70 backdrop-blur-md z-50 flex flex-col items-center justify-center px-4">
          <div className="relative w-64 h-80 bg-amber-900 border-2 border-amber-400/50 rounded-2xl overflow-hidden shadow-2xl">
            <img src={scanningImage} className="w-full h-full object-cover opacity-60" alt="Scanning cover" />
            {/* Scan line animation */}
            <motion.div
              className="absolute left-0 right-0 h-1 bg-amber-400 shadow-[0_0_8px_#fbbf24]"
              animate={{ top: ['0%', '100%', '0%'] }}
              transition={{ repeat: Infinity, duration: 2.5, ease: 'linear' }}
            />
          </div>
          <div className="mt-8 text-center">
            <h3 className="font-heading text-xl text-amber-50 flex items-center justify-center gap-2">
              <Loader2 className="w-5 h-5 animate-spin text-amber-300" />
              Scanning Cover...
            </h3>
            <p className="text-sm text-amber-200/80 mt-2">Reading the cover with AI-powered OCR & metadata enrichment</p>
          </div>
        </div>
      )}

      {/* Book Details Modal */}
      <AnimatePresence>
        {selectedBook && (
          <div
            onClick={() => setSelectedBook(null)}
            className="fixed inset-0 bg-amber-950/40 backdrop-blur-sm z-40 flex items-center justify-center p-4 cursor-pointer"
          >
            <motion.div
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white border border-amber-200 w-full max-w-lg rounded-3xl shadow-2xl p-6 relative overflow-hidden cursor-default max-h-[90vh] overflow-y-auto"
            >
              {/* Cover background glow */}
              <div className="absolute top-0 right-0 w-32 h-32 bg-amber-300/20 rounded-full blur-2xl pointer-events-none"></div>

              <div className="flex justify-between items-start gap-4">
                <div>
                  <h2 className="font-serif text-2xl font-bold text-stone-800">{selectedBook.title}</h2>
                  <p className="text-stone-500 font-semibold mt-1">by {selectedBook.author}</p>
                </div>
                <button
                  type="button"
                  id="close-details-btn"
                  onClick={() => setSelectedBook(null)}
                  className="min-h-[36px] min-w-[36px] p-1.5 bg-amber-50 hover:bg-amber-100 text-stone-500 rounded-xl transition duration-150 cursor-pointer flex-shrink-0"
                  aria-label="Close details modal"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {selectedBook.genre && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="px-3 py-1 bg-amber-100 border border-amber-200 text-amber-800 text-xs font-semibold rounded-full">
                    {selectedBook.genre}
                  </span>
                </div>
              )}

              <div className="mt-6 border-t border-amber-100 pt-4">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/70">Synopsis</h4>
                <p className="font-serif text-stone-600 text-sm mt-2 leading-relaxed">
                  {selectedBook.description || 'No description available.'}
                </p>
              </div>

              {/* Status Selectors */}
              <div className="mt-6 border-t border-amber-100 pt-4">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-amber-700/70 mb-3">Reading Status</h4>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { key: 'unread', label: 'Unread', color: 'bg-stone-100 hover:bg-stone-200 text-stone-600 border-stone-200' },
                    { key: 'reading', label: 'Reading', color: 'bg-amber-100 hover:bg-amber-200 text-amber-700 border-amber-300' },
                    { key: 'read', label: 'Completed', color: 'bg-emerald-100 hover:bg-emerald-200 text-emerald-700 border-emerald-300' }
                  ].map((btn) => {
                    const active = selectedBook.status === btn.key;
                    return (
                      <button
                        key={btn.key}
                        onClick={() => handleUpdateStatus(btn.key)}
                        className={`min-h-[44px] py-2 px-3 text-xs border font-semibold rounded-xl transition duration-150 cursor-pointer ${active ? 'bg-amber-600 text-white border-amber-600' : btn.color}`}
                      >
                        {btn.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Edit / Delete (plain user-initiated REST actions - the agent/LLM never touches these) */}
              <div className="mt-6 border-t border-amber-100 pt-4 flex gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setEditForm({
                      title: selectedBook.title || '',
                      author: selectedBook.author || '',
                      genre: selectedBook.genre || '',
                      description: selectedBook.description || '',
                      status: selectedBook.status || 'unread'
                    });
                    setIsManualEntry(true);
                    setEditingBookId(selectedBook.id);
                    setEditingScannedIndex(null);
                    setSelectedBook(null);
                    setShowEditModal(true);
                  }}
                  className="flex-1 min-h-[44px] py-2.5 bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-200 font-semibold rounded-xl transition duration-150 cursor-pointer"
                >
                  Edit Book
                </button>
                <button
                  type="button"
                  onClick={handleDeleteBook}
                  className="flex-1 min-h-[44px] py-2.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 font-semibold rounded-xl transition duration-150 cursor-pointer"
                >
                  Remove from Shelf
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Edit Form Modal (HITL Draft & Manual Entry & Existing Book Edit) */}
      <AnimatePresence>
        {showEditModal && (
          <div
            onClick={() => { setShowEditModal(false); setEditingBookId(null); setEditingScannedIndex(null); }}
            className="fixed inset-0 bg-amber-950/40 backdrop-blur-sm z-40 flex items-center justify-center p-4 cursor-pointer"
          >
            <motion.div
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white border border-amber-200 w-full max-w-md rounded-3xl shadow-2xl p-6 relative cursor-default max-h-[90vh] overflow-y-auto"
            >
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="font-heading text-xl text-amber-900">
                    {editingBookId ? 'Edit Book' : (isManualEntry ? 'Add Manual Book' : 'Review Cover Draft')}
                  </h2>
                  <p className="text-xs text-stone-500 mt-1">
                    {editingBookId ? 'Update this book\'s details' : (isManualEntry ? 'Bypasses AI processing' : 'Please verify metadata fields')}
                  </p>
                </div>
                <button
                  type="button"
                  id="close-edit-btn"
                  onClick={() => { setShowEditModal(false); setEditingBookId(null); setEditingScannedIndex(null); }}
                  className="min-h-[36px] min-w-[36px] p-1.5 bg-amber-50 hover:bg-amber-100 text-stone-500 rounded-xl transition duration-150 cursor-pointer flex-shrink-0"
                  aria-label="Close edit modal"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleSaveBook} className="space-y-4">
                <div>
                  <label htmlFor="book-title-input" className="block text-xs font-semibold uppercase tracking-wide text-amber-700/70 mb-1.5">Book Title</label>
                  <input
                    type="text"
                    required
                    id="book-title-input"
                    name="title"
                    value={editForm.title}
                    onChange={(e) => setEditForm(prev => ({ ...prev, title: e.target.value }))}
                    className="w-full min-h-[44px] bg-amber-50/60 border border-amber-200 rounded-xl py-2 px-3 text-base sm:text-sm text-stone-800 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400"
                  />
                </div>

                <div>
                  <label htmlFor="book-author-input" className="block text-xs font-semibold uppercase tracking-wide text-amber-700/70 mb-1.5">Author</label>
                  <input
                    type="text"
                    required
                    id="book-author-input"
                    name="author"
                    value={editForm.author}
                    onChange={(e) => setEditForm(prev => ({ ...prev, author: e.target.value }))}
                    className="w-full min-h-[44px] bg-amber-50/60 border border-amber-200 rounded-xl py-2 px-3 text-base sm:text-sm text-stone-800 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400"
                  />
                </div>

                <div>
                  <label htmlFor="book-genre-input" className="block text-xs font-semibold uppercase tracking-wide text-amber-700/70 mb-1.5">Genre</label>
                  <select
                    id="book-genre-input"
                    name="genre"
                    value={editForm.genre}
                    onChange={(e) => setEditForm(prev => ({ ...prev, genre: e.target.value }))}
                    className="w-full min-h-[44px] bg-amber-50/60 border border-amber-200 rounded-xl py-2 px-3 text-base sm:text-sm text-stone-800 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400"
                  >
                    <option value="">Select a genre...</option>
                    {GENRES.map((g) => (
                      <option key={g} value={g}>{g}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label htmlFor="book-description-input" className="block text-xs font-semibold uppercase tracking-wide text-amber-700/70 mb-1.5">Description / Synopsis</label>
                  <textarea
                    rows={3}
                    id="book-description-input"
                    name="description"
                    value={editForm.description}
                    onChange={(e) => setEditForm(prev => ({ ...prev, description: e.target.value }))}
                    className="w-full bg-amber-50/60 border border-amber-200 rounded-xl py-2 px-3 text-base sm:text-sm text-stone-800 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400 resize-none"
                  />
                </div>

                <div className="pt-4 flex gap-3">
                  <button
                    type="button"
                    onClick={() => { setShowEditModal(false); setEditingBookId(null); setEditingScannedIndex(null); }}
                    className="flex-1 min-h-[44px] py-2.5 bg-stone-100 hover:bg-stone-200 text-stone-600 font-semibold rounded-xl transition duration-150 cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="flex-1 min-h-[44px] py-2.5 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white font-bold rounded-xl transition duration-150 shadow-lg shadow-amber-900/15 cursor-pointer"
                  >
                    {editingBookId ? 'Save Changes' : 'Save to Shelf'}
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

    </div>
  );
}
